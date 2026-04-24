"""
Sam's Club deals scraper.
Primary: httpx + parse embedded JSON in page HTML (no Playwright needed).
Sam's Club renders full product data in a script tag in the HTML source.
Fallback: Playwright with stealth.
"""
import asyncio
import json
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SAMS_DEALS_URL = "https://www.samsclub.com/s/deals"
SAMS_GROCERY_URL = "https://www.samsclub.com/b/groceries/1534"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def scrape_sams_club_deals(zip_code: str) -> list[dict[str, Any]]:
    deals = await _fetch_via_httpx(zip_code)
    if deals:
        return deals

    logger.warning("Sam's Club httpx returned nothing — trying Playwright fallback")
    return await _fetch_via_playwright(zip_code)


# ─────────────────────────────────────────────────────────────────────────────
# Primary: httpx + embedded JSON extraction
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_httpx(zip_code: str) -> list[dict[str, Any]]:
    all_deals: list[dict] = []
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=25.0, follow_redirects=True, http2=False
    ) as client:
        for url in [SAMS_DEALS_URL, SAMS_GROCERY_URL]:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug("Sam's Club %s returned %s", url, resp.status_code)
                    continue
                items = _extract_items_from_html(resp.text)
                deals = [d for d in (_normalize(i) for i in items) if d]
                logger.info(
                    "Sam's Club httpx: %d deals from %s for zip=%s", len(deals), url, zip_code
                )
                all_deals.extend(deals)
            except Exception as e:
                logger.error("Sam's Club httpx failed for %s: %s", url, e)

    # Deduplicate by source_id
    seen: set[str] = set()
    unique = []
    for d in all_deals:
        sid = d.get("source_id", "")
        if sid and sid not in seen:
            seen.add(sid)
            unique.append(d)
        elif not sid:
            unique.append(d)
    return unique


def _extract_items_from_html(html: str) -> list[dict]:
    """Find the embedded Next.js page data and pull product items from it."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        content = script.string or ""
        if "memberPrice" not in content and "wasPrice" not in content:
            continue
        match = re.search(r'^\s*(\{"props".*)', content, re.DOTALL)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
        except Exception:
            continue
        pp = data.get("props", {}).get("pageProps", {})
        sr = (pp.get("initialData") or {}).get("searchResult", {})
        stacks = sr.get("itemStacks", [])
        items = []
        for stack in stacks:
            raw = stack.get("itemsV2") or stack.get("items") or []
            if raw:
                items.extend(raw)
        return items
    return []


def _normalize(item: dict) -> dict | None:
    name = (item.get("name") or item.get("displayName") or item.get("itemDescription") or "").strip()
    if not name:
        return None

    pi = item.get("priceInfo") or {}
    sale_price = _to_float(item.get("price") or pi.get("offerPrice"))
    was_price_text = pi.get("wasPrice") or pi.get("listPrice") or ""
    original_price = _to_float(was_price_text) or None

    savings_amt = pi.get("savingsAmt") or 0
    # Only include items that are actually on sale
    if not (original_price or (savings_amt and float(savings_amt) > 0)):
        return None

    # Compute discount pct
    discount_pct = None
    if sale_price and original_price and original_price > 0:
        discount_pct = round((1 - sale_price / original_price) * 100, 1)
    elif savings_amt and sale_price:
        orig = sale_price + float(savings_amt)
        if orig > 0:
            discount_pct = round(float(savings_amt) / orig * 100, 1)
            original_price = orig

    # Image: use usItemId with Sam's Club CDN pattern
    us_item_id = item.get("usItemId") or item.get("itemNumber") or ""
    image_url = None
    if us_item_id:
        image_url = (
            f"https://scene7.samsclub.com/is/image/samsclub/{us_item_id}_1"
            "?wid=400&hei=400&fmt=pjpeg"
        )

    quantity = item.get("salesUnit") or item.get("unitOfMeasure") or item.get("packSize")

    return {
        "raw_title": name,
        "raw_price": str(pi.get("linePrice") or f"${sale_price:.2f}" if sale_price else ""),
        "sale_price": sale_price,
        "original_price": original_price,
        "discount_pct": discount_pct,
        "quantity": str(quantity) if quantity else None,
        "image_url": image_url,
        "source": "samsclub_html",
        "source_id": str(item.get("id") or item.get("usItemId") or ""),
        "is_active": True,
        "_merchant_name": "Sam's Club",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fallback: Playwright
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_playwright(zip_code: str) -> list[dict[str, Any]]:
    intercepted: list[dict] = []
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except (ImportError, ModuleNotFoundError):
            logger.warning("Sam's Club Playwright: playwright-stealth unavailable")

        async def handle_response(response):
            if response.status != 200:
                return
            url = response.url
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and any(
                    k in url for k in ("graphql", "product", "search", "deals", "savings")
                ):
                    data = await response.json()
                    _extract_sams_items(data, intercepted)
            except Exception as e:
                logger.debug("Sam's Club PW response error %s: %s", url, e)

        page.on("response", handle_response)

        try:
            await page.goto(SAMS_DEALS_URL, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
        except Exception as e:
            logger.error("Sam's Club Playwright failed: %s", e)
        finally:
            await browser.close()

    return [_normalize_pw(item) for item in intercepted if item]


def _extract_sams_items(data: Any, output: list) -> None:
    if isinstance(data, list):
        for item in data:
            _extract_sams_items(item, output)
    elif isinstance(data, dict):
        has_name = any(k in data for k in ("name", "title", "displayName", "itemDescription"))
        has_price = any(k in data for k in ("price", "offerPrice", "salePrice", "memberPrice"))
        if has_name and has_price:
            output.append(data)
            return
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_sams_items(v, output)


def _normalize_pw(item: dict) -> dict | None:
    name = (
        item.get("name") or item.get("title") or item.get("displayName")
        or item.get("itemDescription") or ""
    ).strip()
    if not name:
        return None
    price = _to_float(item.get("price") or item.get("memberPrice") or item.get("offerPrice"))
    orig = _to_float(item.get("listPrice") or item.get("wasPrice") or item.get("originalPrice"))
    return {
        "raw_title": name,
        "raw_price": f"${price:.2f}" if price else "",
        "sale_price": price,
        "original_price": orig,
        "image_url": item.get("imageUrl") or item.get("thumbnail"),
        "source": "playwright_sams_club",
        "source_id": str(item.get("itemNumber") or item.get("id") or ""),
        "is_active": True,
        "_merchant_name": "Sam's Club",
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    prices = re.findall(r"\d+\.?\d*", str(value))
    try:
        return float(prices[0]) if prices else None
    except Exception:
        return None


if __name__ == "__main__":
    async def test():
        deals = await scrape_sams_club_deals("78701")
        print(f"Got {len(deals)} Sam's Club deals")
        for d in deals[:5]:
            print(f"  {d['raw_title'][:50]} — ${d['sale_price']} (was ${d['original_price']})")
    asyncio.run(test())

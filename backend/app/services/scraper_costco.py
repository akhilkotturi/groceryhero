"""
Costco hot buys / grocery deals scraper.
Primary: direct httpx + BeautifulSoup (Playwright gets HTTP/2 blocked by Costco's CDN).
Fallback: Playwright with domcontentloaded (shorter timeout, stealth applied).
"""
import asyncio
import logging
import re
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

_COSTCO_PAGES = [
    "https://www.costco.com/hot-buys.html",
    "https://www.costco.com/grocery-household.html",
]


async def scrape_costco_deals(zip_code: str) -> list[dict[str, Any]]:
    # Playwright first — Costco returns 403 to plain httpx requests
    deals = await _fetch_via_playwright(zip_code)
    if deals:
        return deals

    logger.warning("Costco Playwright returned nothing — trying httpx fallback")
    return await _fetch_via_httpx(zip_code)


# ─────────────────────────────────────────────────────────────────────────────
# Primary: direct httpx + BeautifulSoup
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_httpx(zip_code: str) -> list[dict[str, Any]]:
    deals: list[dict] = []
    # Use HTTP/1.1 explicitly — Costco blocks Playwright via HTTP/2 but plain HTTP works
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=25.0, follow_redirects=True, http2=False
    ) as client:
        for url in _COSTCO_PAGES:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug("Costco %s returned %s", url, resp.status_code)
                    continue
                page_deals = _parse_html(resp.text, url)
                logger.info(
                    "Costco httpx: %d deals from %s for zip=%s", len(page_deals), url, zip_code
                )
                deals.extend(page_deals)
            except Exception as e:
                logger.error("Costco httpx fetch failed for %s: %s", url, e)

    return deals


def _parse_html(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    deals: list[dict] = []

    card_selectors = [
        ".product-list-item",
        ".product-tile",
        "[class*='ProductCard']",
        "[class*='tile--product']",
        "[data-testid*='product']",
    ]
    cards = []
    for sel in card_selectors:
        cards = soup.select(sel)
        if cards:
            break

    # Also try the structured product data embedded in JSON-LD or __NEXT_DATA__
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            ld = json.loads(script.string or "")
            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                if item.get("@type") in ("Product", "Offer"):
                    deal = _normalize_ld_item(item)
                    if deal:
                        deals.append(deal)
        except Exception:
            pass

    if deals:
        return deals

    for card in cards[:60]:
        name_el = (
            card.select_one(".description")
            or card.select_one("[class*='product-name']")
            or card.select_one("[class*='productDescription']")
            or card.select_one("h2")
            or card.select_one("h3")
        )
        price_el = (
            card.select_one("[class*='your-price']")
            or card.select_one("[class*='sale-price']")
            or card.select_one("[class*='price']:not([class*='original']):not([class*='was'])")
        )
        orig_el = (
            card.select_one("[class*='original-price']")
            or card.select_one("[class*='was-price']")
            or card.select_one("s")
            or card.select_one("del")
        )
        img_el = card.select_one("img[src], img[data-src]")

        name = name_el.get_text(strip=True) if name_el else ""
        if not name:
            continue

        price_text = price_el.get_text(strip=True) if price_el else ""
        orig_text = orig_el.get_text(strip=True) if orig_el else ""
        img = None
        if img_el:
            img = img_el.get("src") or img_el.get("data-src")

        deals.append(_normalize_card({
            "productDescription": name,
            "price_text": price_text,
            "orig_price_text": orig_text,
            "image_url": img,
        }))

    return deals


def _normalize_ld_item(item: dict) -> dict | None:
    name = item.get("name", "").strip()
    if not name:
        return None
    offers = item.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = _to_float(offers.get("price") or item.get("price"))
    return {
        "raw_title": name,
        "raw_price": f"${price:.2f}" if price else "",
        "sale_price": price,
        "original_price": None,
        "image_url": item.get("image"),
        "source": "costco_httpx",
        "source_id": str(item.get("sku") or item.get("productID") or ""),
        "is_active": True,
        "_merchant_name": "Costco",
    }


def _normalize_card(item: dict) -> dict:
    name = (
        item.get("productDescription") or item.get("productName")
        or item.get("itemDescription") or item.get("name") or ""
    )
    price_text = item.get("price_text") or str(item.get("yourPrice") or item.get("salePrice") or "")
    orig_text = item.get("orig_price_text") or str(item.get("regularPrice") or "")
    return {
        "raw_title": str(name).strip(),
        "raw_price": price_text,
        "sale_price": _to_float(price_text),
        "original_price": _to_float(orig_text),
        "image_url": item.get("image_url") or item.get("thumbnail") or item.get("imageURL"),
        "source": "costco_httpx",
        "source_id": str(item.get("itemNumber") or item.get("productId") or item.get("id") or ""),
        "is_active": True,
        "_merchant_name": "Costco",
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
                "--disable-http2",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except (ImportError, ModuleNotFoundError):
            logger.warning("Costco Playwright: playwright-stealth unavailable")

        async def handle_response(response):
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            # Catch ALL JSON from costco.com — product data comes through various internal APIs
            try:
                data = await response.json()
                _extract_costco_items(data, intercepted)
            except Exception as e:
                logger.debug("Costco PW response parse error: %s", e)

        page.on("response", handle_response)

        _COSTCO_URLS = [
            "https://www.costco.com/hot-buys.html",
            "https://www.costco.com/grocery-household.html",
            "https://www.costco.com/food-and-beverages.html",
        ]
        try:
            for url in _COSTCO_URLS:
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(2000)
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await page.wait_for_timeout(800)
                if intercepted:
                    break
        except Exception as e:
            logger.error("Costco Playwright failed: %s", e)
        finally:
            await browser.close()

    return [_normalize_card(i) for i in intercepted if i]


def _extract_costco_items(data: Any, output: list) -> None:
    if isinstance(data, list):
        for item in data:
            _extract_costco_items(item, output)
    elif isinstance(data, dict):
        has_name = any(
            k in data for k in ("productDescription", "productName", "itemDescription", "name")
        )
        has_price = any(
            k in data for k in ("price", "salePrice", "offerPrice", "yourPrice", "finalPrice")
        )
        if has_name and has_price:
            output.append(data)
            return
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_costco_items(v, output)


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
        deals = await scrape_costco_deals("78701")
        print(f"Got {len(deals)} Costco deals")
        for d in deals[:5]:
            print(f"  {d['raw_title']} — ${d['sale_price']}")
    asyncio.run(test())

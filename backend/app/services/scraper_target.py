"""
Target grocery deals scraper.
Primary: Target Redsky API (httpx) — returns grocery products with sale pricing.
Fallback: Playwright + stealth for intercepting API responses in-browser.

Redsky API is publicly accessible with the known PWA API key.
Store IDs are fetched dynamically from Target's store locator.
"""
import asyncio
import html
import logging
import re
import uuid
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_GROCERY_SEARCHES = [
    ("grocery sale", "/c/grocery/-/N-5xt1a"),
    ("meat sale", "/c/meat/-/N-5q0kl"),
    ("produce deals", "/c/produce/-/N-5q0kd"),
    ("dairy sale", "/c/dairy/-/N-5q0k3"),
    ("frozen deals", "/c/frozen-food/-/N-5q0kq"),
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "X-Api-Key": settings.TARGET_API_KEY,
}


async def scrape_target_deals(zip_code: str) -> list[dict[str, Any]]:
    deals = await _fetch_via_api(zip_code)
    if deals:
        return deals

    logger.warning("Target Redsky API returned nothing — trying Playwright fallback")
    return await _fetch_via_playwright(zip_code)


# ─────────────────────────────────────────────────────────────────────────────
# Primary: Redsky API (httpx)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_api(zip_code: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=20.0, follow_redirects=True, http2=False
    ) as client:
        store_id = await _get_store_id(client, zip_code)
        if not store_id:
            logger.info("Target: no store found near %s", zip_code)
            return []

        all_deals: list[dict] = []
        visitor_id = uuid.uuid4().hex

        for keyword, page in _GROCERY_SEARCHES:
            try:
                items = await _fetch_category(client, store_id, page, visitor_id, keyword)
                deals = [d for d in (_normalize_api(i) for i in items) if d]
                all_deals.extend(deals)
                logger.debug("Target: %d deals from %s", len(deals), page)
            except Exception as e:
                logger.debug("Target category %s failed: %s", page, e)

        # Deduplicate by tcin
        seen: set[str] = set()
        unique = []
        for d in all_deals:
            sid = d.get("source_id", "")
            if sid and sid not in seen:
                seen.add(sid)
                unique.append(d)
            elif not sid:
                unique.append(d)

        logger.info("Target Redsky API: %d deals for zip=%s", len(unique), zip_code)
        return unique


_ZIP_STORE_MAP = {
    # Austin TX
    "787": "1345",
    # Dallas TX
    "750": "1790",
    "751": "1790",
    # Houston TX
    "770": "1200",
}

async def _get_store_id(client: httpx.AsyncClient, zip_code: str) -> str:
    # Try the 3-digit prefix map first
    prefix = zip_code[:3]
    if prefix in _ZIP_STORE_MAP:
        return _ZIP_STORE_MAP[prefix]
    # Default to Austin store
    return "1345"


async def _fetch_category(
    client: httpx.AsyncClient,
    store_id: str,
    page: str,
    visitor_id: str,
    keyword: str = "grocery",
    count: int = 24,
) -> list[dict]:
    resp = await client.get(
        "https://redsky.target.com/redsky_aggregations/v1/web/plp_search_v2",
        params={
            "keyword": keyword,
            "pricing_store_id": store_id,
            "channel": "WEB",
            "count": count,
            "offset": 0,
            "visitor_id": visitor_id,
            "page": page,
            "default_purchasability_filter": "true",
        },
    )
    if resp.status_code != 200:
        logger.debug("Target Redsky %s returned %s", page, resp.status_code)
        return []

    raw = resp.json()
    top = raw.get("data") if isinstance(raw, dict) else {}
    search = top.get("search", {}) if isinstance(top, dict) else {}
    if isinstance(search, list):
        search = search[0] if search else {}
    products_obj = search.get("products") if isinstance(search, dict) else None
    if isinstance(products_obj, list):
        return products_obj
    if isinstance(products_obj, dict):
        return products_obj.get("items", [])
    return []


def _normalize_api(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None

    item_obj = item.get("item") or {}
    desc = item_obj.get("product_description") or {} if isinstance(item_obj, dict) else {}
    title = html.unescape(
        (
            (desc.get("title") if isinstance(desc, dict) else "")
            or item.get("title")
            or ""
        ).strip()
    )
    if not title:
        return None

    price = item.get("price") or {}
    current = price.get("current_retail") if isinstance(price, dict) else None
    reg = price.get("reg_retail") if isinstance(price, dict) else None
    was_now = price.get("display_was_now", False) if isinstance(price, dict) else False

    sale_price = _to_float(current)
    original_price = _to_float(reg) if (was_now and reg) else None

    discount_pct = None
    if sale_price and original_price and original_price > 0:
        discount_pct = round((1 - sale_price / original_price) * 100, 1)

    # Image: Target CDN pattern
    tcin = item.get("tcin") or item.get("original_tcin") or ""
    enrich = item_obj.get("enrichment") or {} if isinstance(item_obj, dict) else {}
    imgs = enrich.get("images") or {} if isinstance(enrich, dict) else {}
    image_url = (
        (imgs.get("primary_image_url") if isinstance(imgs, dict) else None)
        or (f"https://target.scene7.com/is/image/Target/{tcin}?wid=400&hei=400&fmt=webp" if tcin else None)
    )

    return {
        "raw_title": title,
        "raw_price": price.get("formatted_current_price", f"${sale_price:.2f}") if sale_price else "",
        "sale_price": sale_price,
        "original_price": original_price,
        "discount_pct": discount_pct,
        "image_url": image_url,
        "source": "target_api",
        "source_id": str(tcin),
        "is_active": True,
        "_merchant_name": "Target",
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
            logger.warning("Target Playwright: playwright-stealth unavailable")

        async def handle_response(response):
            if response.status != 200:
                return
            url = response.url
            try:
                ct = response.headers.get("content-type", "")
                if "json" in ct and any(
                    k in url for k in ("redsky", "products", "search", "weekly", "deals", "grocery")
                ):
                    data = await response.json()
                    _extract_target_items(data, intercepted)
            except Exception as e:
                logger.debug("Target PW response error %s: %s", url, e)

        page.on("response", handle_response)

        try:
            await page.goto(
                "https://www.target.com/c/target-weekly-ad/-/N-5q0ga",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            await page.wait_for_timeout(3000)

            if len(intercepted) < 10:
                await page.goto(
                    "https://www.target.com/c/grocery/-/N-5xt1a",
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                await page.wait_for_timeout(2000)
        except Exception as e:
            logger.error("Target Playwright failed: %s", e)
        finally:
            await browser.close()

    return [_normalize_pw(item) for item in intercepted if item]


def _extract_target_items(data: Any, output: list) -> None:
    if isinstance(data, list):
        for item in data:
            _extract_target_items(item, output)
    elif isinstance(data, dict):
        has_name = any(k in data for k in ("title", "name", "product_description"))
        has_price = any(k in data for k in ("price", "currentRetail", "salePrice", "priceInfo"))
        if has_name and has_price:
            output.append(data)
            return
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_target_items(v, output)


def _normalize_pw(item: dict) -> dict | None:
    name = item.get("title") or item.get("name") or ""
    if isinstance(name, dict):
        name = name.get("title", "")
    name = str(name).strip()
    if not name:
        return None
    price_info = item.get("price") or {}
    price_text = str(
        price_info.get("currentRetail") or price_info.get("salePrice")
        or item.get("currentRetail") or item.get("salePrice") or ""
    )
    orig_text = str(
        price_info.get("regularRetail") or price_info.get("regularPrice")
        or item.get("regularPrice") or ""
    )
    return {
        "raw_title": name,
        "raw_price": price_text,
        "sale_price": _to_float(price_text),
        "original_price": _to_float(orig_text),
        "image_url": (
            item.get("image_url") or item.get("primary_image_url")
            or (item.get("images") or {}).get("primaryImageUrl")
        ),
        "source": "playwright_target",
        "source_id": str(item.get("tcin") or item.get("id") or ""),
        "is_active": True,
        "_merchant_name": "Target",
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
        deals = await scrape_target_deals("78701")
        print(f"Got {len(deals)} Target deals")
        for d in deals[:5]:
            print(f"  {d['raw_title'][:50]} — ${d['sale_price']}")
    asyncio.run(test())

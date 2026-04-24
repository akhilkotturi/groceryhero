"""
HEB weekly deals scraper.
Primary: HEB's commerce API (httpx, no browser needed).
Fallback: Playwright DOM scrape.

HEB's Incapsula/Imperva protection only covers the main web page render;
the JSON commerce API endpoints work with standard headers.
"""
import asyncio
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HEB_API = "https://www.heb.com/commerce-api/v1"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.heb.com/",
    "x-requested-with": "XMLHttpRequest",
}


async def scrape_heb_deals(zip_code: str) -> list[dict[str, Any]]:
    # Playwright first — HEB's domain is behind Incapsula which blocks httpx entirely
    deals = await _fetch_via_playwright(zip_code)
    if deals:
        return deals

    logger.warning("HEB Playwright returned nothing for %s — trying commerce API", zip_code)
    return await _fetch_via_commerce_api(zip_code)


# ─────────────────────────────────────────────────────────────────────────────
# Primary: HEB commerce API (httpx)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_commerce_api(zip_code: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(headers=_HEADERS, timeout=20.0, follow_redirects=True) as client:
        store_id = await _get_store_id(client, zip_code)
        if not store_id:
            return []
        return await _get_sale_products(client, store_id, zip_code)


async def _get_store_id(client: httpx.AsyncClient, zip_code: str) -> str | None:
    # Try two known store-locator paths
    endpoints = [
        f"{HEB_API}/store/locator/by-zip",
        "https://www.heb.com/heb-plus/store-locator/by-zip",
    ]
    params_options = [
        {"zip": zip_code, "limit": 3},
        {"zipCode": zip_code, "limit": 3},
    ]
    for url, params in zip(endpoints, params_options):
        try:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct:
                    continue
                data = resp.json()
                stores = (
                    data.get("data")
                    or data.get("stores")
                    or (data if isinstance(data, list) else [])
                )
                if stores:
                    store = stores[0]
                    sid = store.get("id") or store.get("storeId") or store.get("store_id")
                    if sid:
                        logger.info("HEB: found store id=%s for zip=%s", sid, zip_code)
                        return str(sid)
        except Exception as e:
            logger.debug("HEB store locator %s failed: %s", url, e)
    return None


async def _get_sale_products(
    client: httpx.AsyncClient, store_id: str, zip_code: str
) -> list[dict[str, Any]]:
    search_endpoints = [
        (
            f"{HEB_API}/product/search",
            {"query": "", "store": store_id, "offset": 0, "count": 60, "include": "promotions"},
        ),
        (
            f"{HEB_API}/product/search",
            {"query": "", "store": store_id, "count": 60, "filters": "promotion_only:true"},
        ),
        (
            "https://www.heb.com/api/v2/weekly-ad/items",
            {"storeId": store_id},
        ),
    ]
    for url, params in search_endpoints:
        try:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.debug("HEB %s returned %s", url, resp.status_code)
                continue
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                logger.debug("HEB %s returned HTML, not JSON", url)
                continue
            data = resp.json()
            products = (
                data.get("products")
                or data.get("items")
                or data.get("data")
                or (data if isinstance(data, list) else [])
            )
            if not products:
                continue
            deals = [d for d in (_normalize_heb_product(p) for p in products) if d]
            logger.info("HEB: %d deals from commerce API for zip=%s", len(deals), zip_code)
            return deals
        except Exception as e:
            logger.debug("HEB product endpoint %s failed: %s", url, e)

    logger.info("HEB: commerce API found no deals for zip=%s", zip_code)
    return []


def _normalize_heb_product(p: dict) -> dict | None:
    name = (
        p.get("name") or p.get("title") or p.get("description")
        or p.get("productName") or ""
    ).strip()
    if not name:
        return None

    # Look for promotion/sale price in nested structure
    sale_price: float | None = None
    original_price: float | None = None

    promo = p.get("promotions") or p.get("promotion") or {}
    if isinstance(promo, list) and promo:
        promo = promo[0]
    if isinstance(promo, dict):
        sale_price = _to_float(promo.get("displayPrice") or promo.get("price"))

    pricing = p.get("pricing") or p.get("price") or {}
    if isinstance(pricing, dict):
        sale_price = sale_price or _to_float(pricing.get("sale") or pricing.get("salePrice"))
        original_price = _to_float(
            pricing.get("regular") or pricing.get("regularPrice") or pricing.get("original")
        )
    elif isinstance(pricing, (int, float)):
        original_price = original_price or float(pricing)

    # Fallback scalar fields
    sale_price = sale_price or _to_float(p.get("salePrice") or p.get("currentPrice"))
    original_price = original_price or _to_float(p.get("regularPrice") or p.get("originalPrice"))

    images = p.get("images") or []
    image_url = None
    if isinstance(images, list) and images:
        img = images[0]
        image_url = img.get("url") or img.get("src") if isinstance(img, dict) else str(img)
    elif isinstance(images, str):
        image_url = images

    return {
        "raw_title": name,
        "raw_price": f"${sale_price:.2f}" if sale_price else "",
        "sale_price": sale_price,
        "original_price": original_price,
        "image_url": image_url or p.get("imageUrl") or p.get("image"),
        "source": "heb_api",
        "source_id": str(p.get("id") or p.get("productId") or p.get("sku") or ""),
        "is_active": True,
        "_merchant_name": "HEB",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fallback: Playwright (minimal — domcontentloaded, short timeout)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_playwright(zip_code: str) -> list[dict[str, Any]]:
    intercepted_raw: list[dict] = []
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except (ImportError, ModuleNotFoundError):
            logger.warning("HEB Playwright: playwright-stealth unavailable")

        async def handle_response(response):
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            # Catch ALL JSON from heb.com — product data comes through various internal endpoints
            try:
                data = await response.json()
                _extract_heb_items(data, intercepted_raw)
            except Exception:
                pass

        page.on("response", handle_response)

        _HEB_URLS = [
            "https://www.heb.com/deals-offers/",
            "https://www.heb.com/weekly-ads",
            "https://www.heb.com/heb-plus/promotions",
        ]
        for url in _HEB_URLS:
            try:
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(2000)
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await page.wait_for_timeout(800)
                if intercepted_raw:
                    break
            except Exception as e:
                logger.debug("HEB Playwright %s failed: %s", url, e)

        await browser.close()

    deals = [_normalize_heb_item(item) for item in intercepted_raw if item]
    logger.info("HEB Playwright: %d deals for %s", len(deals), zip_code)
    return deals


def _extract_heb_items(data: Any, output: list) -> None:
    """Recursively find product-shaped objects in HEB JSON responses."""
    if isinstance(data, list):
        for item in data:
            _extract_heb_items(item, output)
    elif isinstance(data, dict):
        has_name = any(k in data for k in ("name", "title", "description", "productName"))
        has_price = any(k in data for k in ("price", "salePrice", "currentPrice", "promotions", "pricing"))
        if has_name and has_price:
            output.append(data)
            return
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_heb_items(v, output)


def _normalize_heb_item(item: dict) -> dict:
    name = item.get("name") or item.get("title") or item.get("description", "")
    price_text = item.get("price_text") or item.get("displayPrice") or item.get("salePrice", "")
    return {
        "raw_title": str(name).strip(),
        "raw_price": str(price_text),
        "sale_price": _to_float(price_text),
        "image_url": item.get("image_url") or item.get("imageUrl"),
        "source": "playwright_heb",
        "source_id": str(item.get("id", "")),
        "is_active": True,
        "_merchant_name": "HEB",
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
        deals = await scrape_heb_deals("78701")
        print(f"Got {len(deals)} HEB deals")
        for d in deals[:5]:
            print(f"  {d['raw_title']} — ${d['sale_price']}")
    asyncio.run(test())

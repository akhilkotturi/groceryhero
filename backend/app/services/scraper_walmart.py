"""
Walmart grocery deals scraper.
Primary: parse __NEXT_DATA__ JSON from Walmart's browse/food page (no Playwright needed).
Fallback: Playwright + stealth mode with broad JSON interception.
"""
import asyncio
import json
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_WALMART_BROWSE_URLS = [
    "https://www.walmart.com/browse/food/976759",
    "https://www.walmart.com/browse/beverages/976760",
]


async def scrape_walmart_deals(zip_code: str) -> list[dict[str, Any]]:
    deals = await _fetch_via_next_data(zip_code)
    if deals:
        return deals

    logger.warning("Walmart __NEXT_DATA__ returned nothing — trying Playwright fallback")
    return await _fetch_via_playwright(zip_code)


# ─────────────────────────────────────────────────────────────────────────────
# Primary: parse __NEXT_DATA__ from Walmart browse pages (httpx, no browser)
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_via_next_data(zip_code: str) -> list[dict[str, Any]]:
    deals: list[dict] = []
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=25.0, follow_redirects=True, http2=False
    ) as client:
        for url in _WALMART_BROWSE_URLS:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug("Walmart %s returned %s", url, resp.status_code)
                    continue
                page_deals = _parse_next_data(resp.text)
                if page_deals:
                    logger.info(
                        "Walmart httpx __NEXT_DATA__: %d deals from %s for zip=%s",
                        len(page_deals), url, zip_code,
                    )
                    deals.extend(page_deals)
            except Exception as e:
                logger.error("Walmart httpx fetch failed for %s: %s", url, e)
    return deals


def _parse_next_data(html: str) -> list[dict]:
    idx = html.find('id="__NEXT_DATA__"')
    if idx == -1:
        return []
    json_start = html.find(">", idx) + 1
    json_end = html.find("</script>", json_start)
    if json_end == -1:
        return []
    try:
        data = json.loads(html[json_start:json_end])
    except (json.JSONDecodeError, ValueError):
        return []

    search_result = (
        data.get("props", {})
        .get("pageProps", {})
        .get("initialData", {})
        .get("searchResult", {})
    )
    item_stacks = search_result.get("itemStacks", [])
    deals = []
    seen_ids: set[str] = set()
    for stack in item_stacks:
        for item in (stack.get("items") or []) + (stack.get("itemsV2") or []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("usItemId") or item.get("id") or "")
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            deal = _normalize_next_item(item)
            if deal and deal["raw_title"]:
                deals.append(deal)
    return deals


def _normalize_next_item(item: dict) -> dict:
    name = (
        item.get("name") or item.get("title") or item.get("displayName")
        or item.get("shortDescription") or ""
    )
    price_info = item.get("priceInfo") or {}
    sale_price = _parse_price(
        str(item.get("price") or price_info.get("linePrice") or price_info.get("itemPrice") or "")
    )
    orig_price = _parse_price(str(price_info.get("wasPrice") or price_info.get("itemPrice") or ""))
    image_url = None
    for img_field in ("image", "imageInfo", "thumbnail"):
        img = item.get(img_field)
        if isinstance(img, str):
            image_url = img
            break
        if isinstance(img, dict):
            image_url = img.get("thumbnailUrl") or img.get("url")
            if image_url:
                break

    return {
        "raw_title": str(name).strip(),
        "raw_price": price_info.get("linePriceDisplay") or str(sale_price or ""),
        "sale_price": sale_price,
        "original_price": orig_price if orig_price != sale_price else None,
        "image_url": image_url,
        "source": "walmart_httpx",
        "source_id": str(item.get("usItemId") or item.get("id") or ""),
        "is_active": True,
        "_merchant_name": "Walmart",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fallback: Playwright with broad JSON interception
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
                "--disable-infobars",
                "--window-size=1280,800",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
        except (ImportError, ModuleNotFoundError):
            logger.warning("playwright-stealth not installed — running without stealth")

        async def handle_response(response):
            if response.status != 200:
                return
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                data = await response.json()
                _extract_walmart_items(data, intercepted)
            except Exception as e:
                logger.debug("Walmart PW response parse error %s: %s", response.url, e)

        page.on("response", handle_response)

        try:
            for url in _WALMART_BROWSE_URLS:
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(2000)
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await page.wait_for_timeout(800)
                if len(intercepted) >= 10:
                    break
        except Exception as e:
            logger.error("Walmart Playwright failed: %s", e)
        finally:
            await browser.close()

    logger.info("Walmart Playwright: %d raw items scraped for %s", len(intercepted), zip_code)
    return [_normalize_playwright_item(item) for item in intercepted if item]


def _extract_walmart_items(data: Any, output: list) -> None:
    if isinstance(data, list):
        for item in data:
            _extract_walmart_items(item, output)
    elif isinstance(data, dict):
        has_name = any(k in data for k in ("name", "title", "displayName", "productName"))
        has_price = any(k in data for k in ("price", "priceInfo", "currentPrice", "salePrice", "priceNumeric"))
        if has_name and has_price:
            output.append(data)
        else:
            for v in data.values():
                if isinstance(v, (dict, list)):
                    _extract_walmart_items(v, output)


def _normalize_playwright_item(item: dict) -> dict:
    name = (item.get("name") or item.get("title") or item.get("displayName")
            or item.get("productName") or "")
    price_info = item.get("priceInfo") or {}
    price_text = str(
        item.get("price") or item.get("currentPrice") or item.get("salePrice")
        or price_info.get("currentPrice") or "")
    orig_text = str(
        item.get("wasPrice") or item.get("listPrice") or item.get("originalPrice")
        or price_info.get("wasPrice") or "")

    return {
        "raw_title": str(name).strip(),
        "raw_price": price_text,
        "sale_price": _parse_price(price_text),
        "original_price": _parse_price(orig_text),
        "image_url": item.get("image_url") or item.get("imageUrl") or item.get("image"),
        "source": "playwright_walmart",
        "source_id": str(item.get("itemId") or item.get("id") or item.get("productId") or ""),
        "is_active": True,
        "_merchant_name": "Walmart",
    }


def _parse_price(text: str) -> float | None:
    prices = re.findall(r"\d+\.?\d*", str(text))
    try:
        return float(prices[0]) if prices else None
    except Exception:
        return None


if __name__ == "__main__":
    async def test():
        deals = await scrape_walmart_deals("78701")
        print(f"Got {len(deals)} Walmart deals")
        for d in deals[:5]:
            print(f"  {d['raw_title']} — ${d['sale_price']}")
    asyncio.run(test())

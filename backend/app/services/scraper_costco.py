"""
Costco hot buys / featured grocery scraper — Playwright + stealth mode.
"""
import asyncio
import logging
import re
from typing import Any

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


async def scrape_costco_deals(zip_code: str) -> list[dict[str, Any]]:
    logger.info("Costco scraper starting for zip=%s", zip_code)
    intercepted: list[dict] = []

    async with async_playwright() as p:
        logger.info("Costco: launching Chromium")
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()

        try:
            from playwright_stealth import stealth_async
            await stealth_async(page)
            logger.info("Costco: stealth mode applied")
        except ImportError:
            logger.warning("Costco: playwright-stealth not installed — running without stealth")

        async def handle_response(response):
            if response.status != 200:
                return
            url = response.url
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                if any(k in url for k in ("product", "search", "hot", "featured", "catalog", "grocery", "item")):
                    logger.debug("Costco: intercepted JSON from %s", url)
                    data = await response.json()
                    before = len(intercepted)
                    _extract_costco_items(data, intercepted)
                    after = len(intercepted)
                    if after > before:
                        logger.info("Costco: +%d items from %s (total=%d)", after - before, url, after)
            except Exception as e:
                logger.debug("Costco response parse error %s: %s", url, e)

        page.on("response", handle_response)

        try:
            logger.info("Costco: navigating to hot-buys page")
            await page.goto(
                "https://www.costco.com/hot-buys.html",
                wait_until="networkidle",
                timeout=35000,
            )
            await page.wait_for_timeout(3000)
            logger.info("Costco: hot-buys page loaded, intercepted=%d", len(intercepted))

            if len(intercepted) < 10:
                logger.info("Costco: few items from hot-buys, trying grocery-household page")
                await page.goto(
                    "https://www.costco.com/grocery-household.html",
                    wait_until="networkidle",
                    timeout=25000,
                )
                await page.wait_for_timeout(2000)
                logger.info("Costco: grocery-household loaded, intercepted=%d", len(intercepted))

            if not intercepted:
                logger.warning("Costco: no items from network interception, falling back to DOM parse")
                dom_results = await _parse_costco_dom(page)
                logger.info("Costco: DOM parse returned %d items", len(dom_results))
                intercepted.extend(dom_results)

        except Exception as e:
            logger.error("Costco scrape failed: %s", e)
        finally:
            await browser.close()

    logger.info("Costco: scraper finished — %d raw items for zip=%s", len(intercepted), zip_code)
    return [_normalize(item) for item in intercepted if item]


def _extract_costco_items(data: Any, output: list) -> None:
    if isinstance(data, list):
        for item in data:
            _extract_costco_items(item, output)
    elif isinstance(data, dict):
        has_name = any(k in data for k in ("productDescription", "productName", "itemDescription", "name"))
        has_price = any(k in data for k in ("price", "salePrice", "offerPrice", "yourPrice", "finalPrice"))
        if has_name and has_price:
            output.append(data)
            return
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_costco_items(v, output)


async def _parse_costco_dom(page) -> list[dict]:
    """Fallback DOM scraper. Selectors target Costco's current (2024-2025) product card structure."""
    deals = []
    try:
        cards = await page.query_selector_all(
            ".product-list-item, "
            "[class*='product-tile'], "
            "[data-testid*='product'], "
            ".automation-id-product, "
            "[class*='ProductCard'], "
            "[class*='tile--product']"
        )
        logger.info("Costco DOM: found %d candidate card elements", len(cards))

        for card in cards[:60]:
            try:
                name_el = await card.query_selector(
                    ".description, "
                    "[class*='product-name'], "
                    "[class*='productDescription'], "
                    "[data-testid*='title'], "
                    "h2, h3"
                )
                price_el = await card.query_selector(
                    "[class*='your-price'], "
                    "[class*='sale-price'], "
                    "[data-testid*='price'], "
                    "[class*='price']:not([class*='original']):not([class*='was'])"
                )
                orig_el = await card.query_selector(
                    "[class*='original-price'], "
                    "[class*='was-price'], "
                    "[class*='regular-price'], "
                    "s, del"
                )
                img_el = await card.query_selector("img[src], img[data-src]")

                name = (await name_el.inner_text()).strip() if name_el else ""
                price_text = (await price_el.inner_text()).strip() if price_el else ""
                orig_text = (await orig_el.inner_text()).strip() if orig_el else ""
                img = None
                if img_el:
                    img = await img_el.get_attribute("src") or await img_el.get_attribute("data-src")

                if name:
                    deals.append({
                        "productDescription": name,
                        "price_text": price_text,
                        "orig_price_text": orig_text,
                        "image_url": img,
                    })
            except Exception:
                continue

        logger.info("Costco DOM: extracted %d deals from %d cards", len(deals), len(cards))
    except Exception as e:
        logger.error("Costco DOM parse failed: %s", e)
    return deals


def _normalize(item: dict) -> dict:
    name = (item.get("productDescription") or item.get("productName")
            or item.get("itemDescription") or item.get("name") or "")
    price_text = (item.get("price_text") or str(
        item.get("yourPrice") or item.get("salePrice") or item.get("offerPrice")
        or item.get("finalPrice") or item.get("price") or ""))
    orig_text = (item.get("orig_price_text") or str(
        item.get("regularPrice") or item.get("originalPrice") or ""))

    return {
        "raw_title": str(name).strip(),
        "raw_price": str(price_text),
        "sale_price": _parse_price(price_text),
        "original_price": _parse_price(orig_text),
        "image_url": item.get("image_url") or item.get("thumbnail") or item.get("imageURL"),
        "source": "playwright_costco",
        "source_id": str(item.get("itemNumber") or item.get("productId") or item.get("id") or ""),
        "is_active": True,
        "_merchant_name": "Costco",
    }


def _parse_price(text: str) -> float | None:
    prices = re.findall(r"\d+\.?\d*", str(text))
    try:
        return float(prices[0]) if prices else None
    except Exception:
        return None


if __name__ == "__main__":
    async def test():
        deals = await scrape_costco_deals("78701")
        print(f"Got {len(deals)} Costco deals")
        for d in deals[:3]:
            print(d)
    asyncio.run(test())

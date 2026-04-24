"""
Flipp data fetcher for the current public search endpoint.

The legacy /api/flyers route now redirects to the marketing site, but the
search endpoint still returns flyer items for a postal code with an empty query.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FLIPP_SEARCH_SERVER = "https://cdn-gateflipp.flippback.com/bf/flipp/items/search"

# Retail categories that have no business being in a grocery app.
# Checked case-insensitively against the merchant name substring.
_NON_GROCERY_SUBSTRINGS = frozenset([
    "sporting goods", "dick's", "dicks",
    "home depot", "lowe's", "lowes", "ace hardware",
    "hardware", "lumber",
    "petco", "petsmart", "pet store",
    "jcpenney", "j.c. penney",
    "michaels", "michael's",
    "victoria's secret", "victoria secret",
    "lego store", "lego ",
    "ollie's", "ollies",
    "bomgaars",
    "academy sports",
    "best buy", "staples", "office depot",
    "gamestop", "auto zone", "autozone", "o'reilly auto",
    "bath & body", "bath and body",
    "ulta beauty", "sephora",
    "ikea", "kohl's", "kohls",
    "hobby lobby", "jo-ann", "joann", "craft store",
    "bed bath", "crate and barrel", "williams sonoma",
    "furniture", "mattress firm",
])


def is_grocery_merchant(name: str) -> bool:
    """Return False for merchants that are clearly not food/grocery retailers."""
    lower = name.lower()
    for kw in _NON_GROCERY_SUBSTRINGS:
        if kw in lower:
            return False
    return True

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://flipp.com/",
    "Origin": "https://flipp.com",
}


async def fetch_search_results_by_zip(zip_code: str, query: str = "") -> dict[str, Any]:
    """Fetch search results for a postal code using Flipp's active search API."""
    params = {
        "locale": "en",
        "postal_code": zip_code,
        "sid": "",
        "q": query,
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(FLIPP_SEARCH_SERVER, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error(f"Flipp search failed for {zip_code}: {e}")
            return {}


def parse_flipp_item(item: dict, store_id: str) -> dict:
    """Normalize a raw Flipp search item into our Deal schema."""
    sale_price = None
    original_price = None
    discount_pct = None

    price_text = item.get("post_price_text") or item.get("pre_price_text") or ""
    current_price = item.get("current_price")
    original_price_value = item.get("original_price")

    if current_price:
        try:
            sale_price = float(current_price)
        except (ValueError, TypeError):
            pass

    if original_price_value:
        try:
            original_price = float(original_price_value)
        except (ValueError, TypeError):
            pass

    if sale_price and original_price and original_price > 0:
        discount_pct = round((1 - sale_price / original_price) * 100, 1)

    valid_from = None
    valid_to = None
    try:
        if item.get("valid_from"):
            valid_from = datetime.fromisoformat(item["valid_from"].replace("Z", "+00:00"))
        if item.get("valid_to"):
            valid_to = datetime.fromisoformat(item["valid_to"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pass

    return {
        "store_id": store_id,
        "raw_title": item.get("name", ""),
        "raw_description": item.get("description"),
        "raw_price": price_text,
        "sale_price": sale_price,
        "original_price": original_price,
        "discount_pct": discount_pct,
        "quantity": item.get("sale_story"),
        "image_url": item.get("clean_image_url") or item.get("clipping_image_url") or item.get("image_url"),
        "source": "flipp",
        "source_id": str(item.get("flyer_item_id") or item.get("id") or ""),
        "valid_from": valid_from,
        "valid_to": valid_to,
        "is_active": True,
        "_merchant_name": item.get("merchant_name", ""),
        "_merchant_id": item.get("merchant_id"),
        "_flyer_id": item.get("flyer_id"),
    }


async def fetch_all_deals_for_zip(zip_code: str) -> list[dict]:
    """
    Main entry point — fetches all search results for a zip code.
    Returns list of raw deal dicts ready for NLP normalization.
    """
    payload = await fetch_search_results_by_zip(zip_code, query="")

    search_items = payload.get("items", [])
    ecom_items = payload.get("ecom_items", [])
    merchants = payload.get("merchants", [])

    logger.info(
        "Found %d flyer items, %d ecom items, %d merchants for zip %s",
        len(search_items),
        len(ecom_items),
        len(merchants),
        zip_code,
    )

    all_deals: list[dict] = []
    skipped = 0

    for item in search_items:
        merchant = item.get("merchant_name", "")
        if not is_grocery_merchant(merchant):
            skipped += 1
            continue
        all_deals.append(parse_flipp_item(item, store_id="PENDING"))

    for item in ecom_items:
        merchant = item.get("merchant", "")
        if not is_grocery_merchant(merchant):
            skipped += 1
            continue
        all_deals.append(
            {
                "store_id": "PENDING",
                "raw_title": item.get("name") or item.get("description", ""),
                "raw_description": item.get("description"),
                "raw_price": "",
                "sale_price": float(item["current_price"]) if item.get("current_price") is not None else None,
                "original_price": float(item["original_price"]) if item.get("original_price") is not None else None,
                "discount_pct": None,
                "quantity": None,
                "image_url": item.get("image_url"),
                "source": "flipp",
                "source_id": str(item.get("global_id") or item.get("item_id") or item.get("id") or ""),
                "valid_from": None,
                "valid_to": None,
                "is_active": True,
                "_merchant_name": merchant,
                "_merchant_id": item.get("merchant_id"),
                "_flyer_id": item.get("flyer_id"),
            }
        )

    logger.info(
        "Fetched %d grocery deals for zip %s (%d non-grocery skipped)",
        len(all_deals), zip_code, skipped,
    )
    return all_deals

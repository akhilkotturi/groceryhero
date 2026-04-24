"""
Kroger Developer API scraper.
Uses the official Kroger API (developer.kroger.com) — no Playwright needed.

Auth: OAuth 2.0 client credentials (KROGER_CLIENT_ID + KROGER_CLIENT_SECRET).
Free account at developer.kroger.com gives access to:
  - /v1/locations  — nearby stores with coordinates
  - /v1/products   — product catalog with regular + promo pricing

Strategy: query a broad set of grocery search terms, collect items where
promo_price < regular_price (i.e., actually on sale this week).
"""
import asyncio
import base64
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

KROGER_BASE = "https://api.kroger.com/v1"
_TOKEN_CACHE: dict[str, Any] = {}   # {"token": str, "expires_at": float}

# Grocery search terms — broad enough to capture most weekly-ad categories
SEARCH_TERMS = [
    "produce", "meat", "chicken", "beef", "pork", "seafood",
    "dairy", "milk", "eggs", "cheese", "yogurt",
    "bread", "bakery", "deli",
    "frozen", "beverages", "snacks", "cereal",
    "pantry", "canned", "pasta", "sauce",
    "household", "cleaning",
]


# ─────────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────────

async def _get_token(client_id: str, client_secret: str) -> str:
    """Return a cached access token, refreshing when < 60 s from expiry."""
    now = time.time()
    if _TOKEN_CACHE.get("token") and _TOKEN_CACHE.get("expires_at", 0) > now + 60:
        return _TOKEN_CACHE["token"]

    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{KROGER_BASE}/connect/oauth2/token",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": "product.compact"},
        )
        resp.raise_for_status()
        data = resp.json()

    _TOKEN_CACHE["token"] = data["access_token"]
    _TOKEN_CACHE["expires_at"] = now + data.get("expires_in", 1800)
    logger.info("Kroger token refreshed")
    return _TOKEN_CACHE["token"]


# ─────────────────────────────────────────────────────────────────────────────
# Locations
# ─────────────────────────────────────────────────────────────────────────────

async def get_kroger_stores(zip_code: str, token: str, radius_miles: int = 15) -> list[dict]:
    """Return nearby Kroger-family store objects (Kroger, Ralphs, Fred Meyer…)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{KROGER_BASE}/locations",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "filter.zipCode.near": zip_code,
                "filter.radiusInMiles": radius_miles,
                "filter.limit": 10,
            },
        )
        if resp.status_code != 200:
            logger.warning("Kroger locations returned %s", resp.status_code)
            return []
        return resp.json().get("data", [])


# ─────────────────────────────────────────────────────────────────────────────
# Products / deals
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_products_for_term(
    term: str,
    location_id: str,
    token: str,
    client: httpx.AsyncClient,
) -> list[dict]:
    """Fetch one page of products for a search term at a store location."""
    try:
        resp = await client.get(
            f"{KROGER_BASE}/products",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={
                "filter.term": term,
                "filter.locationId": location_id,
                "filter.fulfillment": "sto",
                "filter.limit": 50,
                "filter.start": 0,
            },
        )
        if resp.status_code == 200:
            return resp.json().get("data", [])
        logger.debug("Kroger products %s returned %s", term or "<all>", resp.status_code)
    except Exception as e:
        logger.debug("Kroger product fetch failed for term=%r: %s", term, e)
    return []


def _is_on_sale(product: dict) -> bool:
    """True if at least one item in the product has a promo price below regular."""
    for item in product.get("items", []):
        price = item.get("price") or {}
        regular = price.get("regular")
        promo = price.get("promo")
        if regular is not None and promo is not None and promo < regular:
            return True
    return False


def _normalize_kroger_product(product: dict, location_id: str) -> dict | None:
    """Convert a Kroger API product object to our Deal schema dict."""
    description = product.get("description", "").strip()
    if not description:
        return None

    brand = product.get("brand", "")
    categories = product.get("categories", [])
    category_text = categories[0].lower() if categories else ""

    # Find the on-sale item (prefer promo < regular)
    best_item = None
    best_promo = None
    for item in product.get("items", []):
        price = item.get("price") or {}
        regular = price.get("regular")
        promo = price.get("promo")
        if regular is not None and promo is not None and promo < regular:
            if best_promo is None or promo < best_promo:
                best_item = item
                best_promo = promo

    if not best_item:
        return None

    price_info = best_item.get("price", {})
    regular_price = price_info.get("regular")
    sale_price = price_info.get("promo")
    size = best_item.get("size", "")

    discount_pct = None
    if regular_price and sale_price and regular_price > 0:
        discount_pct = round((1 - sale_price / regular_price) * 100, 1)

    # Best available image (prefer "large" > "medium" > first available)
    image_url = None
    for img in product.get("images", []):
        for sz in sorted(img.get("sizes", []), key=lambda s: {"large": 0, "medium": 1}.get(s.get("size", ""), 2)):
            image_url = sz.get("url")
            if image_url:
                break
        if image_url:
            break

    return {
        "raw_title": description,
        "raw_description": f"{brand} {description}".strip() if brand else description,
        "raw_price": f"${sale_price:.2f}" if sale_price else "",
        "normalized_name": description,
        "brand": brand or None,
        "category": category_text or None,
        "sale_price": float(sale_price) if sale_price is not None else None,
        "original_price": float(regular_price) if regular_price is not None else None,
        "discount_pct": discount_pct,
        "quantity": size or None,
        "image_url": image_url,
        "source": "kroger_api",
        "source_id": product.get("productId", ""),
        "is_active": True,
        "_merchant_name": "Kroger",
        "_location_id": location_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_kroger_deals(zip_code: str) -> list[dict[str, Any]]:
    """
    Fetch this week's Kroger deals for stores near zip_code.
    Requires KROGER_CLIENT_ID and KROGER_CLIENT_SECRET in settings.
    """
    try:
        from app.core.config import settings
        client_id = getattr(settings, "KROGER_CLIENT_ID", "")
        client_secret = getattr(settings, "KROGER_CLIENT_SECRET", "")
    except Exception:
        client_id = ""
        client_secret = ""

    if not client_id or not client_secret:
        logger.warning("KROGER_CLIENT_ID / KROGER_CLIENT_SECRET not set — skipping Kroger API")
        return []

    try:
        token = await _get_token(client_id, client_secret)
    except Exception as e:
        logger.error("Kroger auth failed: %s", e)
        return []

    # Get nearby stores
    stores = await get_kroger_stores(zip_code, token)
    if not stores:
        logger.info("No Kroger stores found near %s", zip_code)
        return []

    # Use the closest store for product queries
    closest = stores[0]
    location_id = closest.get("locationId", "")
    if not location_id:
        return []

    # Extract real store coordinates from the API response
    geo = closest.get("geolocation", {})
    addr = closest.get("address", {})
    _store_meta = {
        "_store_name": closest.get("name", "Kroger"),
        "_store_address": addr.get("addressLine1", "Unknown"),
        "_store_city": addr.get("city", ""),
        "_store_state": addr.get("state", ""),
        "_store_lat": geo.get("latitude"),
        "_store_lng": geo.get("longitude"),
    }

    logger.info("Fetching Kroger deals for location %s (near %s)", location_id, zip_code)

    # Fetch products across all search terms concurrently (rate-limit: 5 at a time)
    seen_product_ids: set[str] = set()
    all_products: list[dict] = []

    sem = asyncio.Semaphore(5)

    async def fetch_guarded(term: str, client: httpx.AsyncClient):
        async with sem:
            return await _fetch_products_for_term(term, location_id, token, client)

    async with httpx.AsyncClient(timeout=20.0) as client:
        results = await asyncio.gather(
            *[fetch_guarded(t, client) for t in SEARCH_TERMS],
            return_exceptions=True,
        )

    for batch in results:
        if isinstance(batch, Exception):
            continue
        for product in batch:
            pid = product.get("productId")
            if pid and pid not in seen_product_ids and _is_on_sale(product):
                seen_product_ids.add(pid)
                all_products.append(product)

    logger.info("Found %d on-sale Kroger products near %s", len(all_products), zip_code)

    deals = []
    for product in all_products:
        normalized = _normalize_kroger_product(product, location_id)
        if normalized:
            normalized.update(_store_meta)
            deals.append(normalized)

    return deals


if __name__ == "__main__":
    async def test():
        deals = await scrape_kroger_deals("78701")
        print(f"Got {len(deals)} Kroger deals")
        for d in deals[:5]:
            print(f"  {d['raw_title']} — sale ${d['sale_price']} / orig ${d['original_price']}")
    asyncio.run(test())

"""
Indian / ethnic grocery deal fetchers.

Both patelbrothers.com (parked domain) and indiabazaar.com (wrong domain) are
inaccessible.  Instead, we pull Indian and Asian grocery deals by filtering the
bulk Flipp fetch for the zip code — a single API call, no per-query rate-limiting.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

_INDIAN_KEYWORDS = [
    "basmati", "lentil", "ghee", "turmeric", "curry", "paneer",
    "chapati", "naan", "dal ", " dal", "chickpea", "masala",
    "biryani", "samosa", "chutney", "tikka", "palak",
    "mango pickle", "tamarind", "cardamom", "cumin", "coriander",
]
_ASIAN_KEYWORDS = [
    "soy sauce", "miso", "ramen", "tofu", "bok choy",
    "kimchi", "jasmine rice", "sesame oil", "sriracha",
    "hoisin", "oyster sauce", "rice noodle", "dumpling", "wonton",
    "dashi", "tempura", "teriyaki", "ponzu", "edamame",
]


def _filter_by_keywords(deals: list[dict], keywords: list[str]) -> list[dict]:
    """Return deals whose title or description contains any keyword."""
    matches: list[dict] = []
    for deal in deals:
        text = (
            (deal.get("raw_title") or "")
            + " "
            + (deal.get("raw_description") or "")
        ).lower()
        if any(kw in text for kw in keywords):
            matches.append(deal)
    return matches


async def _bulk_flipp_deals(zip_code: str) -> list[dict]:
    """One Flipp API call that returns all deals for the zip code."""
    from app.services.flipp import fetch_all_deals_for_zip
    try:
        return await fetch_all_deals_for_zip(zip_code)
    except Exception as e:
        logger.debug("Flipp bulk fetch failed for %s: %s", zip_code, e)
        return []


async def scrape_patel_brothers_deals(zip_code: str) -> list[dict[str, Any]]:
    """
    South Asian grocery deals — filter from bulk Flipp fetch.
    (patelbrothers.com is a parked domain; Flipp is the reliable source.)
    """
    all_deals = await _bulk_flipp_deals(zip_code)
    matches = _filter_by_keywords(all_deals, _INDIAN_KEYWORDS)
    logger.info("Indian Flipp filter: %d/%d deals for %s", len(matches), len(all_deals), zip_code)
    return matches


async def scrape_india_bazaar_deals(zip_code: str) -> list[dict[str, Any]]:
    """
    Asian grocery deals — filter from bulk Flipp fetch.
    (indiabazaar.com resolves to an unrelated company; Flipp covers H Mart etc.)
    """
    all_deals = await _bulk_flipp_deals(zip_code)
    matches = _filter_by_keywords(all_deals, _ASIAN_KEYWORDS)
    logger.info("Asian Flipp filter: %d/%d deals for %s", len(matches), len(all_deals), zip_code)
    return matches

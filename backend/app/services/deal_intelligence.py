"""
Deal Intelligence service — two responsibilities:

1. DealParser (rule-based, zero latency)
   Parses raw deal text to extract the *effective per-unit price* after any
   promotion math:  BOGO → original/2,  "2/$5" → $2.50,  per-lb stays as-is.

2. ItemMatcher (Claude-backed, one batched API call per plan request)
   Filters semantic false positives — e.g. "muscle milk" is NOT a match for
   "milk", "milk bone" is NOT a match for "milk" — without LangChain overhead.
   Falls back silently to returning all candidates when no API key is set or
   the call fails.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Deal type classification
# ─────────────────────────────────────────────────────────────────────────────

class DealType(str, Enum):
    REGULAR = "regular"
    BOGO = "bogo"               # buy 1 get 1 free  → eff = orig / 2
    BUY_GET_FREE = "buy_get_free"   # buy N get M free → eff = (N * orig) / (N+M)
    MULTI_PRICE = "multi_price"     # 2/$5, 3 for $10  → eff = total / count
    PER_LB = "per_lb"           # price is per pound (can't compare directly)
    PER_OZ = "per_oz"           # price is per ounce


@dataclass
class ParsedDeal:
    deal_type: DealType = DealType.REGULAR
    effective_price: float | None = None  # None for per-lb/per-oz — no direct comparison
    price_note: str | None = None         # human-readable label shown in UI
    quantity_required: int = 1            # minimum units to trigger the deal


# ─────────────────────────────────────────────────────────────────────────────
# Compiled regex patterns
# ─────────────────────────────────────────────────────────────────────────────

_BOGO = re.compile(
    r'\b(bogo|b1g1|buy\s*1\s*get\s*1|buy\s*one\s*get\s*one)\b',
    re.I,
)
_BUY_GET_FREE = re.compile(
    r'buy\s*(\d+)\s*get\s*(\d+)\s*(?:free)?',
    re.I,
)
_MULTI_PRICE = re.compile(
    r'(\d+)\s*(?:for|\/)\s*\$?\s*(\d+\.?\d*)',
    re.I,
)
_PER_LB = re.compile(r'\/\s*lb\b|per\s*lb\b|per\s*pound\b|\$[\d.]+\s*lb\b', re.I)
_PER_OZ = re.compile(r'\/\s*oz\b|per\s*oz\b|per\s*ounce\b', re.I)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Public parser function
# ─────────────────────────────────────────────────────────────────────────────

def parse_deal(
    raw_title: str = "",
    raw_price: str = "",
    quantity: str = "",
    sale_price: float | None = None,
    original_price: float | None = None,
) -> ParsedDeal:
    """
    Inspect all text fields for a deal and return the effective per-unit price
    with a human-readable note.

    Examples
    --------
    "Whole Milk BOGO Free", orig=$3.99          → effective=$2.00  note="BOGO ($2.00 each)"
    "Eggs 18ct 2/$5"                            → effective=$2.50  note="2 for $5.00 ($2.50 ea)"
    "Chicken Breast $2.49/lb"                   → effective=None   note="$2.49/lb"
    "Buy 2 Get 1 Free – Yogurt", orig=$1.29     → effective=$0.86  note="Buy 2 Get 1 Free ($0.86 each)"
    "$0 sale, orig=$4.99" (BOGO second item)    → effective=$2.50  note="BOGO ($2.50 each)"
    """
    combined = " ".join(filter(None, [raw_title, raw_price, quantity])).lower()

    # ── Per-unit pricing first (these override deal logic) ───────────────────
    if _PER_LB.search(combined):
        ref = sale_price or original_price
        note = f"${ref:.2f}/lb" if ref else "priced per lb"
        return ParsedDeal(DealType.PER_LB, None, note)

    if _PER_OZ.search(combined):
        ref = sale_price or original_price
        note = f"${ref:.2f}/oz" if ref else "priced per oz"
        return ParsedDeal(DealType.PER_OZ, None, note)

    # ── Multi-price: "2/$5", "3 for $10" ────────────────────────────────────
    mp = _MULTI_PRICE.search(combined)
    if mp:
        count = int(mp.group(1))
        total = float(mp.group(2))
        if count > 0:
            eff = round(total / count, 2)
            return ParsedDeal(
                DealType.MULTI_PRICE,
                eff,
                f"{count} for ${total:.2f} (${eff:.2f} each)",
                count,
            )

    # ── Buy N Get M Free ─────────────────────────────────────────────────────
    bgf = _BUY_GET_FREE.search(combined)
    if bgf:
        buy_n = int(bgf.group(1))
        get_m = int(bgf.group(2))
        total_units = buy_n + get_m
        ref = original_price or sale_price
        if ref and ref > 0 and total_units > 0:
            eff = round((buy_n * ref) / total_units, 2)
            return ParsedDeal(
                DealType.BUY_GET_FREE,
                eff,
                f"Buy {buy_n} Get {get_m} Free (${eff:.2f} each)",
                buy_n,
            )

    # ── BOGO ─────────────────────────────────────────────────────────────────
    if _BOGO.search(combined):
        ref = original_price or sale_price
        if ref and ref > 0:
            eff = round(ref / 2, 2)
            return ParsedDeal(DealType.BOGO, eff, f"BOGO (${eff:.2f} each)", 2)

    # ── Implicit BOGO: sale_price=0, original_price set ──────────────────────
    if sale_price == 0 and original_price and original_price > 0:
        eff = round(original_price / 2, 2)
        return ParsedDeal(DealType.BOGO, eff, f"BOGO (${eff:.2f} each)", 2)

    # ── Regular sale ─────────────────────────────────────────────────────────
    eff = sale_price if sale_price is not None else original_price
    return ParsedDeal(DealType.REGULAR, eff, None, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Groq-backed semantic item matcher
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are a strict grocery shopping assistant.

Task: for each grocery item a shopper wants, decide which candidate deal titles
are **genuine matches** — meaning a shopper intending to buy that item would be
satisfied purchasing the deal product.

Matching rules:
• "milk" → whole milk, 2%, skim, oat milk, almond milk
  ✗ NOT: muscle milk, milk bone, chocolate milk powder (unless item says chocolate)
• "chicken" → chicken breast, thighs, wings, drumsticks, rotisserie chicken
  ✗ NOT: chicken-flavored chips, chicken broth (unless item says broth)
• "eggs" → carton eggs (any size)  ✗ NOT: egg-shaped candy, egg salad kit
• "bread" → sandwich bread, loaves, rolls, sourdough
  ✗ NOT: bread crumbs, stuffing mix
• "butter" → dairy butter, margarine  ✗ NOT: peanut butter, almond butter
• "juice" → bottle/carton juice  ✗ NOT: juice powder, juice concentrate drink mix
• "water" → bottled water  ✗ NOT: sparkling water (unless item says sparkling)
• Generic rule: brand prefixes and suffixes must not change the core product type.
  "Muscle Milk" is a protein supplement, not dairy milk.

Be **conservative** — a false positive (wrong product) is worse than a miss.
Respond with JSON only, no markdown, no explanation outside the JSON.
"""

_USER_PROMPT_TMPL = """\
Items the shopper wants to buy, each with candidate deals from nearby stores:

{items_json}

Return JSON in exactly this format:
{{"results": [{{"item": "...", "matched_ids": ["id_here", ...]}}]}}

Include only the IDs that are genuine matches. An item may have zero matches.
"""


async def filter_matches_with_groq(
    items_to_candidates: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    """
    items_to_candidates: { "milk": [{"id": "...", "title": "Whole Milk Gallon"}, ...], ... }
    Returns:             { "milk": ["deal-id-3", "deal-id-9"], ... }

    Falls back to returning all candidate IDs when:
    - GROQ_API_KEY is not set
    - The Groq call fails for any reason
    """
    fallback = {
        item: [c["id"] for c in candidates]
        for item, candidates in items_to_candidates.items()
    }

    try:
        from app.core.config import settings
        api_key = getattr(settings, "GROQ_API_KEY", None)
        if not api_key:
            logger.debug("GROQ_API_KEY not set — using text-match fallback")
            return fallback

        from groq import AsyncGroq  # lazy import

        client = AsyncGroq(api_key=api_key)

        payload = [
            {
                "item": item,
                "candidates": [{"id": c["id"], "title": c["title"]} for c in candidates],
            }
            for item, candidates in items_to_candidates.items()
        ]

        response = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=1024,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT_TMPL.format(
                    items_json=json.dumps(payload, indent=2)
                )},
            ],
        )

        raw = response.choices[0].message.content.strip()
        parsed = json.loads(raw)
        return {r["item"]: r["matched_ids"] for r in parsed["results"]}

    except Exception as exc:
        logger.warning("Groq item-matching failed, falling back to text match: %s", exc)
        return fallback

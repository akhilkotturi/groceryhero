"""Tool implementations for the RAG agent. Each tool returns a consistent dict shape."""
import logging
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.deal import Deal, Store
from app.models.grocery import GroceryListItem
from app.services.embeddings import embed_batch
from app.services.normalizer import CATEGORY_KEYWORDS

logger = logging.getLogger(__name__)

_TOP_K = 8

# Relevance tuning constants (exported so tests can assert on them)
MIN_COSINE_SIM = 0.12   # low catch-all; LLM does final relevance filtering
COSINE_WEIGHT = 0.85    # semantic relevance is the primary signal
SCORE_WEIGHT = 0.15     # deal quality is a tiebreaker only


_COMMON_STOPWORDS = {
    "a", "an", "and", "any", "are", "at", "best", "buy", "deals", "for", "from", "get", "how",
    "i", "in", "is", "it", "looking", "make", "making", "me", "my", "of", "on", "or", "recipe",
    "recipes", "search", "show", "some", "the", "this", "to", "with",
}



@dataclass
class SearchIntent:
    semantic_queries: list[str]
    keywords: list[str]
    strict_keywords: list[str]
    categories: list[str]
    query_type: str  # recipe | cuisine | category | dietary | product | store | general


def _escape_ilike(value: str) -> str:
    """Escape ILIKE metacharacters (%, _, \\) to prevent pattern injection."""
    return re.sub(r"([%_\\])", r"\\\1", value)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _detect_categories(text: str) -> list[str]:
    lowered = text.lower()
    hits: list[str] = []
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(kw.lower())}\b", lowered) for kw in keywords):
            hits.append(category)
    return hits


def _extract_keywords(query: str) -> list[str]:
    keywords = [tok for tok in _tokenize(query) if tok not in _COMMON_STOPWORDS and len(tok) > 2]
    # Keep insertion order while de-duplicating
    return list(dict.fromkeys(keywords))


def _build_search_intent(query: str, query_type: str = "general") -> SearchIntent:
    keywords = _extract_keywords(query)
    categories = _detect_categories(query)

    # Strict keywords filter candidates to those matching at least one token.
    # - recipe/product: must match ingredient or product name (avoids noise)
    # - cuisine/dietary/category: loose — let embeddings roam the semantic space
    # - store/general: no filtering
    if query_type in {"recipe", "product"}:
        strict_keywords = keywords
    elif query_type == "category":
        strict_keywords = [k for k in keywords if len(k) > 3]  # only meaningful category tokens
    else:
        strict_keywords = []

    if query_type == "recipe" and not categories:
        categories = ["produce", "pantry", "meat", "dairy"]

    semantic_queries = [query]
    if keywords:
        semantic_queries.append(" ".join(keywords[:12]))
    for c in categories[:3]:
        semantic_queries.append(f"{query} {c}")
    semantic_queries = list(dict.fromkeys(q.strip() for q in semantic_queries if q.strip()))

    return SearchIntent(
        semantic_queries=semantic_queries,
        keywords=keywords,
        strict_keywords=strict_keywords,
        categories=list(dict.fromkeys(categories)),
        query_type=query_type,
    )


def _keyword_overlap_score(deal: Deal, keywords: list[str]) -> float:
    if not keywords:
        return 0.0
    haystack = " ".join(filter(None, [deal.normalized_name, deal.raw_title, deal.category, deal.brand])).lower()
    hits = 0
    for kw in keywords:
        if kw in haystack:
            hits += 1
    return min(1.0, hits / max(3, len(keywords)))


def _primary_match_keyword(deal: Deal, keywords: list[str]) -> str | None:
    haystack = " ".join(filter(None, [deal.normalized_name, deal.raw_title, deal.category, deal.brand])).lower()
    for kw in sorted(keywords, key=len, reverse=True):
        if kw and kw in haystack:
            return kw
    return None


def _diversify_recipe_results(scored: list[tuple[float, Deal]], recipe_keywords: list[str], limit: int) -> list[Deal]:
    """
    Prevent recipe retrieval from collapsing onto a single ingredient (e.g. many rice deals).
    Strategy:
    1) Keep top-scored item per ingredient keyword first (coverage pass)
    2) Fill remaining slots by score while capping per-keyword dominance
    """
    if not scored:
        return []

    sorted_scored = sorted(scored, key=lambda x: x[0], reverse=True)
    by_kw: dict[str, list[tuple[float, Deal]]] = {}
    for score, deal in sorted_scored:
        kw = _primary_match_keyword(deal, recipe_keywords)
        if kw:
            by_kw.setdefault(kw, []).append((score, deal))

    selected: list[Deal] = []
    selected_ids: set[str] = set()
    kw_counts: dict[str, int] = {}

    # Pass 1: one best result per matched ingredient keyword.
    for kw in recipe_keywords:
        options = by_kw.get(kw) or []
        if not options:
            continue
        _, deal = options[0]
        if deal.id in selected_ids:
            continue
        selected.append(deal)
        selected_ids.add(deal.id)
        kw_counts[kw] = 1
        if len(selected) >= limit:
            return selected

    # Pass 2: fill by score, but cap over-repetition of same ingredient keyword.
    for _, deal in sorted_scored:
        if deal.id in selected_ids:
            continue
        kw = _primary_match_keyword(deal, recipe_keywords)
        if kw and kw_counts.get(kw, 0) >= 2:
            continue
        selected.append(deal)
        selected_ids.add(deal.id)
        if kw:
            kw_counts[kw] = kw_counts.get(kw, 0) + 1
        if len(selected) >= limit:
            break

    return selected


async def semantic_search(
    query: str,
    db: AsyncSession,
    category: str | None = None,
    store: str | None = None,
    limit: int = _TOP_K,
    query_type: str = "general",
) -> dict[str, Any]:
    """Intent-aware semantic search + lexical rerank for broad grocery queries."""
    intent = _build_search_intent(query, query_type)
    try:
        query_embeddings = await embed_batch(intent.semantic_queries)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return {"success": False, "data": [], "count": 0, "tool": "semantic_search", "error": str(e)}

    candidates: dict[str, Deal] = {}
    for q_emb in query_embeddings:
        stmt = (
            select(Deal)
            .join(Store)
            .options(selectinload(Deal.store))
            .where(and_(Deal.is_active == True, Deal.embedding.is_not(None)))
            .order_by(Deal.embedding.cosine_distance(q_emb))
            .limit(30)
        )
        if category:
            stmt = stmt.where(Deal.category.ilike(f"%{category}%"))
        if store:
            stmt = stmt.where(Store.chain.ilike(f"%{store}%"))
        result = await db.execute(stmt)
        for d in result.scalars().all():
            candidates[d.id] = d

    # Re-rank: cosine_sim is the primary signal; deal_score is a tiebreaker only.
    # A high deal_score must NOT outrank a clearly more relevant item.
    # Embeddings are normalized → dot product = cosine similarity.
    q_arrays = [np.array(q_emb, dtype=np.float32) for q_emb in query_embeddings]

    scored: list[tuple[float, Deal]] = []
    for d in candidates.values():
        emb_arr = np.array(d.embedding, dtype=np.float32)
        cosine_sim = max(float(np.dot(q_arr, emb_arr)) for q_arr in q_arrays)
        if cosine_sim < MIN_COSINE_SIM:
            continue
        keyword_overlap = _keyword_overlap_score(d, intent.keywords)
        if intent.strict_keywords and _keyword_overlap_score(d, intent.strict_keywords) == 0.0:
            continue
        combined = (
            cosine_sim * COSINE_WEIGHT
            + ((d.deal_score or 0.0) / 100.0) * SCORE_WEIGHT
            + keyword_overlap * 0.12
        )
        scored.append((combined, d))

    if intent.query_type == "recipe" and intent.strict_keywords:
        ranked = _diversify_recipe_results(scored, intent.strict_keywords, limit)
    else:
        ranked = [d for _, d in sorted(scored, key=lambda x: x[0], reverse=True)[:limit]]

    # Fall back to keyword ILIKE search when pgvector found nothing OR when every
    # candidate was below the relevance threshold (all noise, no signal).
    if not ranked:
        fallback_filters = []
        for term in list(dict.fromkeys([query] + intent.keywords)):
            escaped = _escape_ilike(term)
            fallback_filters.extend(
                [
                    Deal.normalized_name.ilike(f"%{escaped}%"),
                    Deal.raw_title.ilike(f"%{escaped}%"),
                    Deal.category.ilike(f"%{escaped}%"),
                    Deal.brand.ilike(f"%{escaped}%"),
                ]
            )

        fallback_stmt = (
            select(Deal)
            .join(Store)
            .options(selectinload(Deal.store))
            .where(
                and_(
                    Deal.is_active == True,
                    or_(*fallback_filters),
                )
            )
            .limit(limit)
        )
        fb_result = await db.execute(fallback_stmt)
        deals = fb_result.scalars().all()
        return {
            "success": True,
            "data": [_deal_to_dict(d) for d in deals],
            "count": len(deals),
            "tool": "semantic_search",
            "fallback": True,
        }

    return {
        "success": True,
        "data": [_deal_to_dict(d) for d in ranked],
        "count": len(ranked),
        "tool": "semantic_search",
    }


async def filter_by_store(
    store_name: str,
    db: AsyncSession,
    category: str | None = None,
) -> dict[str, Any]:
    """Return top deals from a specific store chain, sorted by deal_score."""
    stmt = (
        select(Deal)
        .join(Store)
        .options(selectinload(Deal.store))
        .where(and_(Deal.is_active == True, Store.chain.ilike(f"%{store_name}%")))
        .order_by(Deal.deal_score.desc().nullslast())
        .limit(_TOP_K)
    )
    if category:
        stmt = stmt.where(Deal.category.ilike(f"%{category}%"))

    result = await db.execute(stmt)
    deals = result.scalars().all()
    return {"success": True, "data": [_deal_to_dict(d) for d in deals], "count": len(deals), "tool": "filter_by_store"}


async def compare_prices(
    item_name: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Run semantic_search, group by store chain, return lowest price per store."""
    search = await semantic_search(item_name, db, limit=20)
    if not search["success"] or not search["data"]:
        return {"success": False, "data": [], "count": 0, "tool": "compare_prices", "error": "no deals found"}

    by_store: dict[str, dict] = {}
    for deal in search["data"]:
        chain = deal.get("store_chain") or "Unknown"
        price = deal.get("sale_price") or deal.get("unit_price")
        if price is None:
            continue
        if chain not in by_store or price < by_store[chain]["lowest_price"]:
            by_store[chain] = {"store": chain, "lowest_price": price, "deal": deal}

    sorted_stores = sorted(by_store.values(), key=lambda x: x["lowest_price"])
    return {"success": True, "data": sorted_stores, "count": len(sorted_stores), "tool": "compare_prices"}


async def add_to_plan(
    deal_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Add deal to grocery_list_items. Idempotent (UniqueConstraint handles duplicates)."""
    deal_result = await db.execute(select(Deal).options(selectinload(Deal.store)).where(Deal.id == deal_id))
    deal = deal_result.scalar_one_or_none()
    if not deal:
        return {"success": False, "tool": "add_to_plan", "error": f"Deal {deal_id} not found"}

    existing = await db.execute(
        select(GroceryListItem).where(
            and_(GroceryListItem.user_id == user_id, GroceryListItem.deal_id == deal_id)
        )
    )
    if existing.scalar_one_or_none():
        return {"success": True, "tool": "add_to_plan", "message": "Already in plan", "deal": _deal_to_dict(deal)}

    item = GroceryListItem(user_id=user_id, deal_id=deal_id)
    db.add(item)
    await db.flush()
    return {"success": True, "tool": "add_to_plan", "message": "Added to plan", "deal": _deal_to_dict(deal)}


def _deal_to_dict(d: Deal) -> dict:
    return {
        "deal_id": d.id,
        "title": d.normalized_name or d.raw_title,
        "category": d.category,
        "brand": d.brand,
        "sale_price": d.sale_price,
        "unit_price": d.unit_price,
        "original_price": d.original_price,
        "discount_pct": d.discount_pct,
        "deal_score": d.deal_score,
        "store_chain": d.store.chain if d.store else None,
        "store_name": d.store.name if d.store else None,
        "image_url": d.image_url,
        "store_id": d.store_id,
    }

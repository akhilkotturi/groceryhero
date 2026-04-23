"""Tool implementations for the RAG agent. Each tool returns a consistent dict shape."""
import logging
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.deal import Deal, Store
from app.models.grocery import GroceryListItem
from app.services.embeddings import embed

logger = logging.getLogger(__name__)

_TOP_K = 8


async def semantic_search(
    query: str,
    db: AsyncSession,
    category: str | None = None,
    store: str | None = None,
    limit: int = _TOP_K,
) -> dict[str, Any]:
    """Embed query → pgvector cosine search over 20 candidates → re-rank → return top-k."""
    try:
        query_emb = embed(query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return {"success": False, "data": [], "count": 0, "tool": "semantic_search", "error": str(e)}

    stmt = (
        select(Deal)
        .join(Store)
        .options(selectinload(Deal.store))
        .where(and_(Deal.is_active == True, Deal.embedding.is_not(None)))
        .order_by(Deal.embedding.cosine_distance(query_emb))
        .limit(20)
    )
    if category:
        stmt = stmt.where(Deal.category.ilike(f"%{category}%"))
    if store:
        stmt = stmt.where(Store.chain.ilike(f"%{store}%"))

    result = await db.execute(stmt)
    candidates = result.scalars().all()

    if not candidates:
        # Fallback: keyword ILIKE search
        fallback_stmt = (
            select(Deal)
            .join(Store)
            .options(selectinload(Deal.store))
            .where(
                and_(
                    Deal.is_active == True,
                    or_(
                        Deal.normalized_name.ilike(f"%{query}%"),
                        Deal.raw_title.ilike(f"%{query}%"),
                    ),
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

    # Re-rank: cosine_sim * 0.6 + deal_score * 0.4
    # Embeddings are normalized → dot product = cosine similarity
    q_arr = np.array(query_emb, dtype=np.float32)

    def _score(d: Deal) -> float:
        emb_arr = np.array(d.embedding, dtype=np.float32)
        cosine_sim = float(np.dot(q_arr, emb_arr))
        return cosine_sim * 0.6 + ((d.deal_score or 0.0) / 100.0) * 0.4

    ranked = sorted(candidates, key=_score, reverse=True)[:limit]
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

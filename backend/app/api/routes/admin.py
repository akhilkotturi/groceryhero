"""
Admin endpoints — development/ops use only.
Trigger ingestion manually without waiting for the Sunday cron.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.core.redis import get_redis

router = APIRouter()


async def update_scraper_status(scraper_name: str, count: int, error: str | None = None) -> None:
    """Write scraper result to Redis so both the API and worker containers can read it."""
    import json
    from datetime import datetime, timezone
    redis = await get_redis()
    await redis.hset("scraper_status", scraper_name, json.dumps({
        "last_run": datetime.now(timezone.utc).isoformat(),
        "count": count,
        "error": error,
    }))


class IngestRequest(BaseModel):
    zip_codes: list[str] = ["78701", "78704", "78745"]  # Austin defaults


@router.post("/ingest")
async def trigger_ingestion(req: IngestRequest, background_tasks: BackgroundTasks):
    """Kick off deal ingestion for the given zip codes in the background."""
    if not req.zip_codes:
        raise HTTPException(status_code=400, detail="zip_codes must not be empty")

    async def run():
        from app.workers.scheduler import ingest_deals_for_zip
        import asyncio
        import logging
        logger = logging.getLogger(__name__)
        for z in req.zip_codes:
            try:
                logger.info("Admin-triggered ingestion for %s", z)
                await ingest_deals_for_zip(z)
            except Exception as e:
                logger.error("Ingestion failed for %s: %s", z, e)

    background_tasks.add_task(run)
    return {"status": "started", "zip_codes": req.zip_codes}


@router.post("/flush-cache")
async def flush_cache():
    """Flush all Redis deal caches."""
    from app.core.redis import get_redis
    redis = await get_redis()
    keys = await redis.keys("deals:nearby:*")
    if keys:
        await redis.delete(*keys)
    return {"flushed": len(keys)}


@router.get("/scraper-status")
async def scraper_status():
    """Return the last-run result count for each scraper (read from Redis)."""
    import json
    redis = await get_redis()
    raw = await redis.hgetall("scraper_status")
    return {"scrapers": {k: json.loads(v) for k, v in raw.items()}}


@router.post("/fix-store-coordinates")
async def fix_store_coordinates():
    """
    Repair store coordinates using ZIP-constrained geocoding.
    Also applies deterministic per-chain jitter for stores stuck on exact ZIP centroid.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.deal import Store
    from app.workers.scheduler import _geocode_zip_sync, _geocode_store_sync, _haversine_miles, _jitter
    from sqlalchemy import select
    import asyncio, logging
    logger = logging.getLogger(__name__)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Store))
        stores = result.scalars().all()
        updated = 0
        re_geocoded = 0
        jittered = 0
        for store in stores:
            if not store.zip_code or not store.latitude or not store.longitude:
                continue
            zip_lat, zip_lng, _, _ = await asyncio.to_thread(_geocode_zip_sync, store.zip_code)

            # If a store drifted far from its ZIP area, repair it first.
            if zip_lat != 0.0 and _haversine_miles(store.latitude, store.longitude, zip_lat, zip_lng) > 25:
                geo = await asyncio.to_thread(_geocode_store_sync, store.chain or store.name or "", store.zip_code)
                if geo:
                    store.latitude, store.longitude = geo
                    updated += 1
                    re_geocoded += 1
                    continue

            # If still pinned to ZIP centroid, spread by deterministic jitter.
            if abs(store.latitude - zip_lat) < 1e-4 and abs(store.longitude - zip_lng) < 1e-4:
                jlat, jlng = _jitter(store.chain or "", store.zip_code)
                store.latitude = zip_lat + jlat
                store.longitude = zip_lng + jlng
                updated += 1
                jittered += 1
        await session.commit()

    # Flush nearby-deals cache so fresh coordinates are served
    from app.core.redis import get_redis
    redis = await get_redis()
    keys = await redis.keys("deals:nearby:*")
    if keys:
        await redis.delete(*keys)

    logger.info("fix-store-coordinates: updated=%d re_geocoded=%d jittered=%d", updated, re_geocoded, jittered)
    return {
        "updated": updated,
        "re_geocoded": re_geocoded,
        "jittered": jittered,
        "cache_flushed": len(keys) if keys else 0,
    }


@router.post("/backfill-embeddings")
async def backfill_embeddings(background_tasks: BackgroundTasks, force: bool = False):
    """Re-generate embeddings.  force=true re-embeds ALL active deals (needed after build_embed_text changes)."""
    async def run():
        from app.db.session import AsyncSessionLocal
        from app.models.deal import Deal
        from app.services.embeddings import embed_batch, build_embed_text
        from sqlalchemy import select, and_
        import logging
        logger = logging.getLogger(__name__)

        async with AsyncSessionLocal() as session:
            stmt = select(Deal).where(Deal.is_active == True)
            if not force:
                stmt = stmt.where(Deal.embedding.is_(None))
            result = await session.execute(stmt)
            deals = result.scalars().all()
            if not deals:
                logger.info("backfill-embeddings: nothing to do")
                return
            texts = [build_embed_text({
                "normalized_name": d.normalized_name,
                "raw_title": d.raw_title,
                "category": d.category,
                "brand": d.brand,
                "raw_description": d.raw_description,
            }) for d in deals]
            embeddings = await embed_batch(texts)
            for deal, emb in zip(deals, embeddings):
                deal.embedding = emb
            await session.commit()
            logger.info("backfill-embeddings: embedded %d deals (force=%s)", len(deals), force)

    background_tasks.add_task(run)
    return {"status": "started", "force": force, "message": "Backfilling embeddings in background"}


@router.post("/recategorize")
async def recategorize_deals():
    """Re-run category detection on all existing deals and update the DB."""
    from app.db.session import AsyncSessionLocal
    from app.models.deal import Deal
    from app.services.normalizer import detect_category
    from sqlalchemy import select
    import logging
    logger = logging.getLogger(__name__)

    updated = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Deal))
        deals = result.scalars().all()
        for deal in deals:
            text = f"{deal.normalized_name or ''} {deal.raw_title or ''} {deal.raw_description or ''}".strip()
            new_category = detect_category(text)
            if deal.category != new_category:
                deal.category = new_category
                updated += 1
        await session.commit()

    # Flush Redis cache so fresh categories are served immediately
    from app.core.redis import get_redis
    redis = await get_redis()
    keys = await redis.keys("deals:nearby:*")
    if keys:
        await redis.delete(*keys)

    logger.info("Recategorized %d / %d deals", updated, len(deals))
    return {"total": len(deals), "updated": updated, "cache_flushed": len(keys)}


class DebugRagRequest(BaseModel):
    query: str


@router.post("/debug-rag")
async def debug_rag(req: DebugRagRequest):
    """Full RAG trace: classification → search candidates (with cosine scores) → final answer."""
    import numpy as np
    from app.db.session import AsyncSessionLocal
    from app.services.rag import _classify_and_expand, _groq_complete, _SUMMARIZE_PROMPT, _parse_final_response
    from app.services import rag_tools
    from app.services.embeddings import embed_batch
    import json

    async with AsyncSessionLocal() as db:
        classification = await _classify_and_expand(req.query)
        expanded = classification.expanded_query
        search_query = f"{req.query} {expanded}".strip() if expanded and expanded != req.query else req.query

        intent = rag_tools._build_search_intent(search_query, classification.type)
        query_embeddings = await embed_batch(intent.semantic_queries)
        q_arrays = [np.array(q, dtype=np.float32) for q in query_embeddings]

        from sqlalchemy import select, and_
        from sqlalchemy.orm import selectinload
        from app.models.deal import Deal, Store

        candidates: dict[str, Deal] = {}
        for q_emb in query_embeddings:
            stmt = (
                select(Deal).join(Store).options(selectinload(Deal.store))
                .where(and_(Deal.is_active == True, Deal.embedding.is_not(None)))
                .order_by(Deal.embedding.cosine_distance(q_emb))
                .limit(20)
            )
            result = await db.execute(stmt)
            for d in result.scalars().all():
                candidates[d.id] = d

        scored = []
        for d in candidates.values():
            emb_arr = np.array(d.embedding, dtype=np.float32)
            cosine_sim = max(float(np.dot(q_arr, emb_arr)) for q_arr in q_arrays)
            kw_score = rag_tools._keyword_overlap_score(d, intent.keywords)
            scored.append({
                "deal_id": d.id,
                "title": d.normalized_name or d.raw_title,
                "category": d.category,
                "brand": d.brand,
                "store": d.store.chain if d.store else None,
                "cosine_sim": round(cosine_sim, 4),
                "keyword_overlap": round(kw_score, 4),
                "passes_threshold": cosine_sim >= rag_tools.MIN_COSINE_SIM,
                "passes_strict": not intent.strict_keywords or rag_tools._keyword_overlap_score(d, intent.strict_keywords) > 0,
            })

        scored.sort(key=lambda x: x["cosine_sim"], reverse=True)

        return {
            "query": req.query,
            "classification": {
                "type": classification.type,
                "detail": classification.detail,
                "search_terms": classification.search_terms,
            },
            "search_query_used": search_query,
            "semantic_queries": intent.semantic_queries,
            "strict_keywords": intent.strict_keywords,
            "candidates_retrieved": len(scored),
            "top_candidates": scored[:15],
        }

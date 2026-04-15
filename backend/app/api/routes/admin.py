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

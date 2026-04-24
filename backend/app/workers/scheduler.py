"""
APScheduler worker — runs weekly ad ingestion pipeline.
Triggers every Sunday at 11pm (most chains flip ads Monday morning).

Pipeline:
1. Fetch deals from Flipp + Playwright scrapers
2. Run NLP normalization
3. Run ML deal scoring
4. Upsert into Postgres
5. Invalidate Redis cache
"""
import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from functools import lru_cache
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.session import init_db, AsyncSessionLocal
from app.core.redis import init_redis, get_redis
from app.models.deal import Deal, Store
from app.services.flipp import fetch_all_deals_for_zip
from app.services.scraper_heb import scrape_heb_deals
from app.services.scraper_walmart import scrape_walmart_deals
from app.services.scraper_kroger import scrape_kroger_deals
from app.services.scraper_target import scrape_target_deals
from app.services.scraper_costco import scrape_costco_deals
from app.services.scraper_sams_club import scrape_sams_club_deals
from app.services.scraper_indian_grocery import scrape_patel_brothers_deals, scrape_india_bazaar_deals
from app.services.normalizer import batch_normalize
from app.services.scorer import score_batch
from app.services.embeddings import embed_batch, build_embed_text
from app.api.routes.admin import update_scraper_status
from sqlalchemy import select, update, and_
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Zip codes to fetch — in production, derive from all user zip_codes in DB
SEED_ZIP_CODES = ["78701", "78704", "78745", "75001", "75002"]


async def get_active_zip_codes() -> list[str]:
    """Pull distinct zip codes from the users table."""
    from app.models.user import User
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User.zip_code).distinct().where(User.zip_code.is_not(None))
        )
        zips = [r[0] for r in result.all()]
        return zips if zips else SEED_ZIP_CODES


async def get_store_id_by_merchant(
    db,
    merchant_name: str,
    zip_code: str,
    merchant_id: str | int | None = None,
    coord_overrides: dict | None = None,
) -> str | None:
    """Match a merchant name to a store. Fixes bad coordinates (0,0) on each lookup."""
    store = None

    merchant_id_str = str(merchant_id) if merchant_id is not None else None
    if merchant_id_str:
        result = await db.execute(
            select(Store).where(
                and_(
                    Store.flipp_merchant_id == merchant_id_str,
                    Store.zip_code == zip_code,
                    Store.is_active == True,
                )
            ).limit(1)
        )
        store = result.scalar_one_or_none()

    if not store:
        normalized = _normalize_chain_name(merchant_name)
        result = await db.execute(
            select(Store).where(
                and_(
                    Store.zip_code == zip_code,
                    Store.is_active == True,
                )
            )
        )
        candidates = result.scalars().all()
        store = next((s for s in candidates if _normalize_chain_name(s.chain) == normalized), None)

    if not store:
        return None

    zip_lat, zip_lng, _, _ = await asyncio.to_thread(_geocode_zip_sync, zip_code)

    # Heal stores that were persisted with (0, 0) placeholder coordinates,
    # or stores geocoded far away from their serving ZIP area.
    far_from_zip = (
        zip_lat != 0.0
        and _haversine_miles(store.latitude, store.longitude, zip_lat, zip_lng) > 25
    )
    if (store.latitude == 0.0 and store.longitude == 0.0) or far_from_zip:
        ov = coord_overrides or {}
        if ov.get("lat") is not None:
            store.latitude = float(ov["lat"])
            store.longitude = float(ov["lng"])
        else:
            geo = await asyncio.to_thread(_geocode_store_sync, merchant_name, zip_code)
            if geo:
                store.latitude, store.longitude = geo
            else:
                if zip_lat != 0.0:
                    store.latitude, store.longitude = zip_lat, zip_lng

    return store.id


@lru_cache(maxsize=512)
def _geocode_zip_sync(zip_code: str) -> tuple[float, float, str, str]:
    """Resolve a ZIP code to (lat, lng, city, state). Tries zippopotam.us then Nominatim."""
    # Primary: zippopotam.us
    try:
        response = httpx.get(f"https://api.zippopotam.us/us/{zip_code}", timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        place = (payload.get("places") or [{}])[0]
        lat = float(place.get("latitude", 0.0) or 0.0)
        lng = float(place.get("longitude", 0.0) or 0.0)
        if lat != 0.0 and lng != 0.0:
            return lat, lng, place.get("place name", ""), place.get("state abbreviation", "")
    except Exception:
        pass

    # Fallback: Nominatim postal code lookup
    try:
        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"postalcode": zip_code, "country": "us", "format": "json", "limit": 1},
            headers={"User-Agent": "GroceryHero/1.0"},
            timeout=8.0,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"]), "", ""
    except Exception:
        pass

    return 0.0, 0.0, "", ""


@lru_cache(maxsize=1024)
def _geocode_store_sync(merchant_name: str, zip_code: str) -> tuple[float, float] | None:
    """Look up a real store location via Nominatim OSM constrained to ZIP vicinity."""
    try:
        zip_lat, zip_lng, _, _ = _geocode_zip_sync(zip_code)
        viewbox = None
        if zip_lat != 0.0 and zip_lng != 0.0:
            # ~35x35 mile search box around the ZIP centroid.
            dlat = 0.25
            dlng = 0.25
            viewbox = f"{zip_lng-dlng},{zip_lat-dlat},{zip_lng+dlng},{zip_lat+dlat}"

        response = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": merchant_name,
                "postalcode": zip_code,
                "format": "json",
                "limit": 5,
                "countrycodes": "us",
                "addressdetails": "0",
                **({"viewbox": viewbox, "bounded": 1} if viewbox else {}),
            },
            headers={"User-Agent": "GroceryHero/1.0"},
            timeout=8.0,
        )
        response.raise_for_status()
        results = response.json()
        if results:
            merchant_tokens = {
                t for t in merchant_name.lower().replace("'", "").replace("-", " ").split()
                if len(t) >= 3
            }

            best: tuple[float, float] | None = None
            best_dist = float("inf")
            for r in results:
                lat = float(r["lat"])
                lng = float(r["lon"])
                if zip_lat != 0.0 and zip_lng != 0.0:
                    dist = _haversine_miles(lat, lng, zip_lat, zip_lng)
                    if dist > 25:
                        continue
                else:
                    dist = 0.0

                name_blob = (r.get("display_name") or "").lower().replace("'", "").replace("-", " ")
                if merchant_tokens and not all(tok in name_blob for tok in merchant_tokens):
                    continue

                if dist < best_dist:
                    best = (lat, lng)
                    best_dist = dist

            if best:
                return best
    except Exception:
        pass
    return None


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in miles."""
    r = 3958.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalize_chain_name(name: str) -> str:
    """Canonicalize chain names for stable matching."""
    if not name:
        return ""
    lowered = name.lower().replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


async def ensure_store_for_merchant(
    db,
    merchant_name: str,
    zip_code: str,
    merchant_id: str | int | None = None,
    overrides: dict | None = None,
) -> str:
    """Create a store row for a merchant. Geocodes the real store address when possible."""
    zip_lat, zip_lng, zip_city, zip_state = await asyncio.to_thread(_geocode_zip_sync, zip_code)
    ov = overrides or {}

    if ov.get("lat") is not None:
        lat, lng = float(ov["lat"]), float(ov["lng"])
    else:
        # Try to resolve the actual store location (not just zip centroid)
        geo = await asyncio.to_thread(_geocode_store_sync, merchant_name or "", zip_code)
        if geo:
            lat, lng = geo
        else:
            # Zip centroid fallback — clustering handles visual overlap
            lat, lng = zip_lat, zip_lng

    store = Store(
        chain=merchant_name or "Unknown",
        name=ov.get("name", merchant_name) or f"Store {zip_code}",
        address=ov.get("address", "Unknown"),
        city=ov.get("city", zip_city or ""),
        state=ov.get("state", zip_state or ""),
        zip_code=zip_code,
        latitude=lat,
        longitude=lng,
        flipp_merchant_id=str(merchant_id) if merchant_id is not None else None,
        is_active=True,
    )
    db.add(store)
    await db.flush()
    return store.id


async def ingest_deals_for_zip(zip_code: str):
    """Full ingestion pipeline for one zip code."""
    logger.info(f"Starting deal ingestion for zip {zip_code}")

    # 1. Fetch raw deals
    raw_deals = []

    try:
        flipp_deals = await fetch_all_deals_for_zip(zip_code)
        raw_deals.extend(flipp_deals)
        logger.info(f"Flipp: {len(flipp_deals)} deals for {zip_code}")
        await update_scraper_status("flipp", len(flipp_deals))
    except Exception as e:
        logger.error(f"Flipp fetch failed for {zip_code}: {e}")
        await update_scraper_status("flipp", 0, error=str(e))

    try:
        heb_deals = await scrape_heb_deals(zip_code)
        raw_deals.extend(heb_deals)
        logger.info(f"HEB: {len(heb_deals)} deals for {zip_code}")
        await update_scraper_status("heb", len(heb_deals))
    except Exception as e:
        logger.error(f"HEB scrape failed for {zip_code}: {e}")
        await update_scraper_status("heb", 0, error=str(e))

    for scraper_fn, chain_name, scraper_key in [
        (scrape_walmart_deals, "Walmart", "walmart"),
        (scrape_kroger_deals, "Kroger", "kroger"),
        (scrape_target_deals, "Target", "target"),
        (scrape_costco_deals, "Costco", "costco"),
        (scrape_sams_club_deals, "Sam's Club", "sams_club"),
        (scrape_patel_brothers_deals, "Patel Brothers", "patel_brothers"),
        (scrape_india_bazaar_deals, "India Bazaar", "india_bazaar"),
    ]:
        try:
            chain_deals = await scraper_fn(zip_code)
            raw_deals.extend(chain_deals)
            logger.info(f"{chain_name}: {len(chain_deals)} deals for {zip_code}")
            await update_scraper_status(scraper_key, len(chain_deals))
        except Exception as e:
            logger.error(f"{chain_name} scrape failed for {zip_code}: {e}")
            await update_scraper_status(scraper_key, 0, error=str(e))

    if not raw_deals:
        logger.warning(f"No deals fetched for {zip_code}")
        return

    # 2. Normalize
    normalized = batch_normalize(raw_deals)

    # 3. Score
    scored = score_batch(normalized)

    # 3b. Embed deals (run in executor — sentence-transformers is sync)
    try:
        embed_texts = [build_embed_text(d) for d in scored]
        embeddings = await embed_batch(embed_texts)
        for deal_data, emb in zip(scored, embeddings):
            deal_data["embedding"] = emb
        logger.info(f"Embedded {len(embeddings)} deals for {zip_code}")
    except Exception as e:
        logger.warning(f"Embedding failed for {zip_code}: {e} — continuing without embeddings")

    # 4. Upsert into DB
    async with AsyncSessionLocal() as db:
        inserted = 0
        for deal_data in scored:
            merchant = deal_data.pop("_merchant_name", "Unknown")
            merchant_id = deal_data.pop("_merchant_id", None)
            deal_data.pop("_flyer_id", None)
            deal_data.pop("store_id", None)

            # Extract real store coordinates when the scraper provides them
            store_overrides = {
                key[7:]: deal_data.pop(key)
                for key in list(deal_data.keys())
                if key.startswith("_store_")
            }

            store_id = await get_store_id_by_merchant(
                db,
                merchant,
                zip_code,
                merchant_id=merchant_id,
                coord_overrides=store_overrides,
            )
            if not store_id:
                store_id = await ensure_store_for_merchant(
                    db,
                    merchant,
                    zip_code,
                    merchant_id=merchant_id,
                    overrides=store_overrides,
                )

            # Upsert by source_id
            source_id = deal_data.get("source_id")
            if source_id:
                existing = await db.execute(
                    select(Deal).where(
                        and_(
                            Deal.source_id == source_id,
                            Deal.source == deal_data.get("source"),
                        )
                    )
                )
                existing_deal = existing.scalar_one_or_none()
                if existing_deal:
                    for k, v in deal_data.items():
                        if hasattr(existing_deal, k):
                            setattr(existing_deal, k, v)
                    continue

            deal = Deal(store_id=store_id, **{
                k: v for k, v in deal_data.items()
                if hasattr(Deal, k) and k != "store_id"
            })
            db.add(deal)
            inserted += 1

        await db.commit()
        logger.info(f"Inserted {inserted} new deals for {zip_code}")

    # 5. Invalidate Redis cache for this zip
    try:
        redis = await get_redis()
        keys = await redis.keys(f"deals:nearby:*")
        if keys:
            await redis.delete(*keys)
            logger.info(f"Invalidated {len(keys)} cache keys")
    except Exception as e:
        logger.warning(f"Cache invalidation failed: {e}")


async def run_weekly_ingestion():
    """Main job — runs for all active zip codes."""
    logger.info(f"Weekly ingestion started at {datetime.now(timezone.utc)}")
    zip_codes = await get_active_zip_codes()
    logger.info(f"Processing {len(zip_codes)} zip codes: {zip_codes}")

    # Run concurrently but with a semaphore to avoid hammering scrapers
    sem = asyncio.Semaphore(3)

    async def guarded(zip_code):
        async with sem:
            await ingest_deals_for_zip(zip_code)

    await asyncio.gather(*[guarded(z) for z in zip_codes])
    logger.info("Weekly ingestion complete")


async def main():
    await init_db()
    await init_redis()

    scheduler = AsyncIOScheduler()

    # Run every Sunday at 11pm
    scheduler.add_job(
        run_weekly_ingestion,
        CronTrigger(day_of_week="sun", hour=23, minute=0),
        id="weekly_ingestion",
        name="Weekly deal ingestion",
        replace_existing=True,
    )

    # Also run immediately on startup in development
    import os
    if os.getenv("APP_ENV") == "development":
        scheduler.add_job(
            run_weekly_ingestion,
            id="startup_ingestion",
            name="Startup ingestion (dev)",
        )

    scheduler.start()
    logger.info("Scheduler started. Waiting for jobs...")

    try:
        await asyncio.Event().wait()  # Run forever
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

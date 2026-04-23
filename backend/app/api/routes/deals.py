from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from datetime import datetime, timezone
import json
import math

import hashlib
import logging
from app.db.session import get_db
from app.models.deal import Deal, Store
from app.schemas.deal import DealsResponse, DealOut, StoreOut, SearchResponse
from app.schemas.deal import AskRequest, AskResponse, AskDealResult
from app.core.deps import get_current_user
from app.core.redis import get_redis
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

CACHE_TTL = 60 * 30  # 30 minutes


def _escape_ilike(value: str) -> str:
    """Escape ILIKE metacharacters (%, _, \\) to prevent pattern injection."""
    import re
    return re.sub(r"([%_\\])", r"\\\1", value)


@router.get("/nearby", response_model=DealsResponse)
async def get_nearby_deals(
    lat: float = Query(..., description="User latitude"),
    lng: float = Query(..., description="User longitude"),
    radius_miles: float = Query(10.0, le=50),
    category: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, le=100),
    sort_by: str = Query("deal_score", enum=["deal_score", "discount_pct", "sale_price"]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"deals:nearby:{lat:.3f}:{lng:.3f}:{radius_miles}:{category}:{page}:{sort_by}"
    redis = await get_redis()
    cached = await redis.get(cache_key)
    if cached:
        return DealsResponse(**json.loads(cached))

    # Rough bounding box (1 degree lat ≈ 69 miles; longitude shrinks with cos(lat))
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * math.cos(math.radians(lat)))

    now = datetime.now(timezone.utc)
    query = (
        select(Deal)
        .join(Store)
        .options(selectinload(Deal.store))
        .where(
            and_(
                Store.latitude.between(lat - lat_delta, lat + lat_delta),
                Store.longitude.between(lng - lng_delta, lng + lng_delta),
                Deal.is_active == True,
                or_(Deal.valid_to.is_(None), Deal.valid_to >= now),
            )
        )
    )

    if category:
        query = query.where(Deal.category == category)

    # Sorting
    sort_col = getattr(Deal, sort_by, Deal.deal_score)
    query = query.order_by(sort_col.desc().nullslast())

    # Pagination
    total_result = await db.execute(query)
    total = len(total_result.scalars().all())

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    deals = result.scalars().all()

    response = DealsResponse(
        deals=[DealOut.model_validate(d) for d in deals],
        total=total,
        page=page,
        per_page=per_page,
    )

    await redis.setex(cache_key, CACHE_TTL, response.model_dump_json())
    return response


@router.get("/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Deal.category).distinct().where(Deal.category.is_not(None))
    )
    return {"categories": [r[0] for r in result.all()]}


@router.get("/search", response_model=SearchResponse)
async def search_deals(
    q: str = Query(..., min_length=2, description="Search query"),
    lat: float = Query(...),
    lng: float = Query(...),
    radius_miles: float = Query(10.0, le=50),
    category: str | None = Query(None),
    per_page: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * math.cos(math.radians(lat)))
    now = datetime.now(timezone.utc)
    escaped_q = _escape_ilike(q)

    query = (
        select(Deal)
        .join(Store)
        .options(selectinload(Deal.store))
        .where(
            and_(
                Store.latitude.between(lat - lat_delta, lat + lat_delta),
                Store.longitude.between(lng - lng_delta, lng + lng_delta),
                Deal.is_active == True,
                or_(Deal.valid_to.is_(None), Deal.valid_to >= now),
                or_(
                    Deal.normalized_name.ilike(f"%{escaped_q}%"),
                    Deal.raw_title.ilike(f"%{escaped_q}%"),
                ),
            )
        )
        .order_by(Deal.deal_score.desc().nullslast())
    )

    if category:
        query = query.where(Deal.category == category)

    query = query.limit(per_page)

    result = await db.execute(query)
    deals = result.scalars().all()

    return SearchResponse(
        deals=[DealOut.model_validate(d) for d in deals],
        total=len(deals),
        query=q,
    )


@router.post("/ask", response_model=AskResponse)
async def ask_deals(
    request: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"ask:{current_user.id}:{hashlib.md5(request.query.encode()).hexdigest()[:16]}"
    redis = await get_redis()
    cached = await redis.get(cache_key)
    if cached:
        return AskResponse(**json.loads(cached))

    try:
        from app.services.rag import run_agent
        agent_result = await run_agent(request.query, current_user.id, db)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("RAG agent error: %s", e)
        raise HTTPException(status_code=503, detail="Local AI unavailable")

    # Enrich deal references with full DealOut objects
    enriched_deals: list[AskDealResult] = []
    for ref in agent_result.get("deals", []):
        deal_id = ref.get("deal_id", "")
        relevance = ref.get("relevance", "")
        if deal_id:
            deal_row = await db.execute(
                select(Deal).options(selectinload(Deal.store)).where(Deal.id == deal_id)
            )
            deal_obj = deal_row.scalar_one_or_none()
            enriched_deals.append(AskDealResult(
                deal_id=deal_id,
                relevance=relevance,
                deal=DealOut.model_validate(deal_obj) if deal_obj else None,
            ))

    response = AskResponse(
        answer=agent_result.get("answer", ""),
        deals=enriched_deals,
        actions_taken=agent_result.get("actions_taken", []),
        suggested_actions=agent_result.get("suggested_actions", []),
        turns=agent_result.get("turns", 0),
    )

    await redis.setex(cache_key, 300, response.model_dump_json())
    return response


@router.get("/{deal_id}", response_model=DealOut)
async def get_deal(
    deal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Deal).where(Deal.id == deal_id))
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    return DealOut.model_validate(deal)

"""
Grocery Run Planner — simplified deal-ID flow.

The user has already browsed deals and selected specific ones via the "+ Plan"
button on deal cards. This endpoint receives their deal IDs, fetches them from
the DB, parses effective prices with the rule-based DealParser, groups by store,
and returns a structured plan. No Groq call needed.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.deal import Deal, Store
from app.schemas.deal import DealOut, StoreOut
from app.core.deps import get_current_user
from app.models.user import User
from app.services.deal_intelligence import parse_deal

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    deal_ids: list[str]
    lat: float   # reserved for future distance-based store sorting
    lng: float   # reserved for future distance-based store sorting


class PlanMatch(BaseModel):
    deal: DealOut
    effective_price: float | None = None
    deal_type: str = "regular"
    price_note: str | None = None


class StorePlan(BaseModel):
    store: StoreOut
    matches: list[PlanMatch]
    total_price: float
    total_savings: float
    item_count: int


class PlanResponse(BaseModel):
    store_plans: list[StorePlan]
    grand_total: float
    grand_savings: float


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/plan", response_model=PlanResponse)
async def create_plan(
    req: PlanRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not req.deal_ids:
        raise HTTPException(status_code=400, detail="deal_ids must not be empty")

    # ── 1. Fetch all requested deals (with store eager-loaded) ────────────────
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Deal)
        .options(selectinload(Deal.store))
        .where(
            and_(
                Deal.id.in_(req.deal_ids),
                Deal.is_active == True,
                or_(Deal.valid_to.is_(None), Deal.valid_to >= now),
            )
        )
    )
    deals: list[Deal] = result.scalars().all()

    if not deals:
        raise HTTPException(status_code=404, detail="No deals found for the provided IDs")

    # ── 2. Group by store ─────────────────────────────────────────────────────
    store_groups: dict[str, list[Deal]] = {}
    store_objs: dict[str, Store] = {}
    for deal in deals:
        store_groups.setdefault(deal.store_id, []).append(deal)
        store_objs.setdefault(deal.store_id, deal.store)

    # ── 3. Build StorePlan per store ──────────────────────────────────────────
    store_plans: list[StorePlan] = []
    grand_total = 0.0
    grand_savings = 0.0

    for store_id, store_deals in store_groups.items():
        store = store_objs[store_id]
        total_price = 0.0
        total_savings = 0.0
        matches: list[PlanMatch] = []

        for deal in store_deals:
            parsed = parse_deal(
                raw_title=deal.raw_title or "",
                raw_price=deal.raw_price or "",
                quantity=deal.quantity or "",
                sale_price=deal.sale_price,
                original_price=deal.original_price,
            )
            eff = parsed.effective_price
            original = deal.original_price or deal.unit_price
            savings = round(original - eff, 2) if (eff is not None and original and original > eff) else 0.0

            total_price += eff or 0.0
            total_savings += savings

            matches.append(PlanMatch(
                deal=DealOut.model_validate(deal),
                effective_price=round(eff, 2) if eff is not None else None,
                deal_type=parsed.deal_type.value,
                price_note=parsed.price_note,
            ))

        store_plans.append(StorePlan(
            store=StoreOut.model_validate(store),
            matches=matches,
            total_price=round(total_price, 2),
            total_savings=round(total_savings, 2),
            item_count=len(matches),
        ))

        grand_total += total_price
        grand_savings += total_savings

    # Sort: most items first, then cheapest store
    store_plans.sort(key=lambda sp: (-sp.item_count, sp.total_price))

    return PlanResponse(
        store_plans=store_plans,
        grand_total=round(grand_total, 2),
        grand_savings=round(grand_savings, 2),
    )

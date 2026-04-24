import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.db.session import get_db
from app.models.deal import Store, Deal
from app.schemas.deal import StoreOut
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("/nearby", response_model=list[StoreOut])
async def get_nearby_stores(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_miles: float = Query(10.0, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * math.cos(math.radians(lat)))

    result = await db.execute(
        select(Store)
        .join(Deal, Deal.store_id == Store.id)
        .where(
            and_(
                Store.latitude.between(lat - lat_delta, lat + lat_delta),
                Store.longitude.between(lng - lng_delta, lng + lng_delta),
                Store.is_active == True,
                Deal.is_active == True,
                or_(Deal.valid_to.is_(None), Deal.valid_to >= now),
            )
        )
        .distinct()
    )
    stores = result.scalars().all()
    return [StoreOut.model_validate(s) for s in stores]

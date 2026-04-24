from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.grocery import GroceryListItem
from app.models.deal import Deal
from app.schemas.grocery import GroceryListItemOut, GroceryListResponse
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter()


@router.get("", response_model=GroceryListResponse)
async def get_grocery_list(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GroceryListItem)
        .where(GroceryListItem.user_id == current_user.id)
        .options(selectinload(GroceryListItem.deal).selectinload(Deal.store))
        .order_by(GroceryListItem.added_at.desc())
    )
    items = result.scalars().all()
    return GroceryListResponse(
        items=[GroceryListItemOut.model_validate(i) for i in items],
        total=len(items),
    )


@router.post("/{deal_id}", response_model=GroceryListItemOut, status_code=201)
async def add_to_grocery_list(
    deal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    deal_result = await db.execute(select(Deal).where(Deal.id == deal_id))
    if not deal_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Deal not found")

    existing = await db.execute(
        select(GroceryListItem).where(
            GroceryListItem.user_id == current_user.id,
            GroceryListItem.deal_id == deal_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Already in list")

    item = GroceryListItem(user_id=current_user.id, deal_id=deal_id)
    db.add(item)
    await db.flush()

    result = await db.execute(
        select(GroceryListItem)
        .where(GroceryListItem.id == item.id)
        .options(selectinload(GroceryListItem.deal).selectinload(Deal.store))
    )
    return GroceryListItemOut.model_validate(result.scalar_one())


@router.delete("/{deal_id}", status_code=204)
async def remove_from_grocery_list(
    deal_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GroceryListItem).where(
            GroceryListItem.user_id == current_user.id,
            GroceryListItem.deal_id == deal_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Not in list")
    await db.delete(item)

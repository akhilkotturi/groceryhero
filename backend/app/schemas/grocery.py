from pydantic import BaseModel
from datetime import datetime
from app.schemas.deal import DealOut


class GroceryListItemOut(BaseModel):
    id: str
    deal_id: str
    added_at: datetime
    deal: DealOut

    model_config = {"from_attributes": True}


class GroceryListResponse(BaseModel):
    items: list[GroceryListItemOut]
    total: int

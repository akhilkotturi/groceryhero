from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class StoreOut(BaseModel):
    id: str
    chain: str
    name: str
    address: str
    city: str
    state: str
    zip_code: str
    latitude: float
    longitude: float

    model_config = {"from_attributes": True}


class DealOut(BaseModel):
    id: str
    store_id: str
    store: Optional[StoreOut] = None
    raw_title: str
    normalized_name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    unit_price: Optional[float] = None
    original_price: Optional[float] = None
    sale_price: Optional[float] = None
    discount_pct: Optional[float] = None
    quantity: Optional[str] = None
    deal_score: Optional[float] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    image_url: Optional[str] = None
    source: str

    model_config = {"from_attributes": True}


class DealsResponse(BaseModel):
    deals: list[DealOut]
    total: int
    page: int
    per_page: int


class SearchResponse(BaseModel):
    deals: list[DealOut]
    total: int
    query: str

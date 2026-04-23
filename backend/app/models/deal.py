import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, DateTime, Boolean, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from app.db.session import Base


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    chain: Mapped[str] = mapped_column(String, index=True)         # "HEB", "Kroger", "Walmart"
    name: Mapped[str] = mapped_column(String)                      # "HEB - North Lamar"
    address: Mapped[str] = mapped_column(String)
    city: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String(2))
    zip_code: Mapped[str] = mapped_column(String(10), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    flipp_merchant_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    deals: Mapped[list["Deal"]] = relationship("Deal", back_populates="store")


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), index=True)

    # Raw data from scraper
    raw_title: Mapped[str] = mapped_column(String)
    raw_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_price: Mapped[str | None] = mapped_column(String, nullable=True)

    # Normalized by NLP pipeline
    normalized_name: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    original_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    sale_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    discount_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[str | None] = mapped_column(String, nullable=True)   # "2/$5", "3 for $10"

    # ML deal score (0-100)
    deal_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)

    # Validity
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Source
    source: Mapped[str] = mapped_column(String)                    # "flipp", "playwright_heb"
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # RAG embedding (384-dim all-MiniLM-L6-v2)
    embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)

    store: Mapped["Store"] = relationship("Store", back_populates="deals")

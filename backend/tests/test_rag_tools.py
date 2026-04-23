"""Unit tests for RAG tools — uses mock DB session."""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import AsyncMock, MagicMock, patch


def _make_mock_deal(deal_id="d1", name="chicken breast", category="meat",
                    sale_price=3.99, deal_score=80.0, store_chain="HEB"):
    deal = MagicMock()
    deal.id = deal_id
    deal.normalized_name = name
    deal.raw_title = name
    deal.category = category
    deal.brand = None
    deal.sale_price = sale_price
    deal.unit_price = sale_price
    deal.original_price = 5.99
    deal.discount_pct = 33.0
    deal.deal_score = deal_score
    deal.image_url = None
    deal.store_id = "s1"
    deal.is_active = True
    deal.embedding = [0.1] * 384
    store = MagicMock()
    store.chain = store_chain
    store.name = f"{store_chain} - Main St"
    deal.store = store
    return deal


def test_deal_to_dict_shape():
    from app.services.rag_tools import _deal_to_dict
    deal = _make_mock_deal()
    d = _deal_to_dict(deal)
    assert d["deal_id"] == "d1"
    assert d["title"] == "chicken breast"
    assert d["sale_price"] == 3.99
    assert d["store_chain"] == "HEB"


def test_semantic_search_fallback_on_empty_pgvector():
    """If pgvector returns 0 results, falls back to ILIKE and returns success=True."""
    from app.services.rag_tools import semantic_search

    db = AsyncMock()
    # First execute (pgvector) returns empty, second (ILIKE) returns one deal
    deal = _make_mock_deal()
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    ilike_result = MagicMock()
    ilike_result.scalars.return_value.all.return_value = [deal]
    db.execute = AsyncMock(side_effect=[empty_result, ilike_result])

    result = asyncio.run(semantic_search("chicken breast", db))
    assert result["success"] is True
    assert result["tool"] == "semantic_search"


def test_filter_by_store_returns_correct_tool_name():
    from app.services.rag_tools import filter_by_store

    db = AsyncMock()
    deal = _make_mock_deal()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [deal]
    db.execute = AsyncMock(return_value=mock_result)

    result = asyncio.run(filter_by_store("HEB", db))
    assert result["success"] is True
    assert result["tool"] == "filter_by_store"
    assert result["count"] == 1


def test_add_to_plan_already_in_list():
    from app.services.rag_tools import add_to_plan

    db = AsyncMock()
    deal = _make_mock_deal()

    existing_item = MagicMock()
    deal_result = MagicMock()
    deal_result.scalar_one_or_none.return_value = deal
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = existing_item  # already exists

    db.execute = AsyncMock(side_effect=[deal_result, existing_result])

    result = asyncio.run(add_to_plan("d1", "user1", db))
    assert result["success"] is True
    assert "Already" in result["message"]

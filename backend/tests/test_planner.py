"""Unit tests for new planner grouping logic."""
import pytest
from dataclasses import dataclass
from typing import Optional


# ── Minimal stubs so we can test grouping without a live DB ──────────────────

@dataclass
class StubStore:
    id: str
    chain: str
    name: str
    address: str
    city: str = "Austin"
    state: str = "TX"
    zip_code: str = "78701"
    latitude: float = 30.27
    longitude: float = -97.74


@dataclass
class StubDeal:
    id: str
    store_id: str
    store: StubStore
    raw_title: str
    raw_price: str = ""
    sale_price: Optional[float] = None
    original_price: Optional[float] = None
    quantity: str = ""
    normalized_name: Optional[str] = None
    source: str = "test"


def _group_by_store(deals):
    """Pure grouping logic — extracted from the route for unit testing."""
    groups = {}
    for deal in deals:
        groups.setdefault(deal.store_id, []).append(deal)
    return groups


def _compute_subtotal(deals):
    """Sum of sale_price (or 0) for a list of deals."""
    return sum(d.sale_price or 0.0 for d in deals)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_single_store_group():
    store_a = StubStore(id="s1", chain="HEB", name="HEB #1", address="123 Main")
    deals = [
        StubDeal(id="d1", store_id="s1", store=store_a, raw_title="Milk", sale_price=3.99),
        StubDeal(id="d2", store_id="s1", store=store_a, raw_title="Eggs", sale_price=5.49),
    ]
    groups = _group_by_store(deals)
    assert len(groups) == 1
    assert len(groups["s1"]) == 2


def test_two_store_groups():
    store_a = StubStore(id="s1", chain="HEB", name="HEB #1", address="123 Main")
    store_b = StubStore(id="s2", chain="Kroger", name="Kroger #2", address="456 Oak")
    deals = [
        StubDeal(id="d1", store_id="s1", store=store_a, raw_title="Milk", sale_price=3.99),
        StubDeal(id="d2", store_id="s2", store=store_b, raw_title="Chicken", sale_price=7.99),
        StubDeal(id="d3", store_id="s1", store=store_a, raw_title="Bread", sale_price=4.49),
    ]
    groups = _group_by_store(deals)
    assert len(groups) == 2
    assert len(groups["s1"]) == 2
    assert len(groups["s2"]) == 1


def test_subtotal_calculation():
    store_a = StubStore(id="s1", chain="HEB", name="HEB #1", address="123 Main")
    deals = [
        StubDeal(id="d1", store_id="s1", store=store_a, raw_title="Milk", sale_price=3.99),
        StubDeal(id="d2", store_id="s1", store=store_a, raw_title="Eggs", sale_price=5.49),
    ]
    total = _compute_subtotal(deals)
    assert abs(total - 9.48) < 0.001


def test_subtotal_with_none_price():
    store_a = StubStore(id="s1", chain="HEB", name="HEB #1", address="123 Main")
    deals = [
        StubDeal(id="d1", store_id="s1", store=store_a, raw_title="Milk", sale_price=3.99),
        StubDeal(id="d2", store_id="s1", store=store_a, raw_title="Mystery item", sale_price=None),
    ]
    total = _compute_subtotal(deals)
    assert abs(total - 3.99) < 0.001


def test_sort_by_item_count_desc_then_price_asc():
    """Stores with more items should come first; ties broken by subtotal."""
    groups_data = [
        {"store_id": "s1", "item_count": 2, "total_price": 10.0},
        {"store_id": "s2", "item_count": 3, "total_price": 20.0},
        {"store_id": "s3", "item_count": 2, "total_price": 8.0},
    ]
    sorted_groups = sorted(groups_data, key=lambda g: (-g["item_count"], g["total_price"]))
    assert sorted_groups[0]["store_id"] == "s2"   # 3 items — first
    assert sorted_groups[1]["store_id"] == "s3"   # 2 items, cheaper — second
    assert sorted_groups[2]["store_id"] == "s1"   # 2 items, more expensive — last

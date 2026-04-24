"""Unit tests for RAG tools — uses mock DB session."""
import asyncio
import math
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np


# ── helpers ──────────────────────────────────────────────────────────────────

def _unit_vec(size=384, seed=0):
    """Return a deterministic unit vector of the given size."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(size).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


def _vec_with_cosine_sim(reference: list[float], target_sim: float) -> list[float]:
    """
    Build a unit vector whose cosine similarity to `reference` is approximately
    `target_sim`.  Works by interpolating between `reference` and a random
    orthogonal vector.
    """
    ref = np.array(reference, dtype=np.float32)
    # Random orthogonal component
    rng = np.random.default_rng(42)
    rand = rng.standard_normal(len(ref)).astype(np.float32)
    rand -= rand.dot(ref) * ref          # project out the reference direction
    rand /= np.linalg.norm(rand)
    # Linear combo: sim * ref + sqrt(1 - sim²) * orthogonal
    sim = float(np.clip(target_sim, -1.0, 1.0))
    v = sim * ref + math.sqrt(1 - sim ** 2) * rand
    v /= np.linalg.norm(v)
    return v.tolist()


def _make_mock_deal(deal_id="d1", name="chicken breast", category="meat",
                    sale_price=3.99, deal_score=80.0, store_chain="HEB",
                    embedding=None):
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
    deal.embedding = embedding if embedding is not None else _unit_vec()
    store = MagicMock()
    store.chain = store_chain
    store.name = f"{store_chain} - Main St"
    deal.store = store
    return deal


# ── _deal_to_dict ─────────────────────────────────────────────────────────────

def test_deal_to_dict_shape():
    from app.services.rag_tools import _deal_to_dict
    deal = _make_mock_deal()
    d = _deal_to_dict(deal)
    assert d["deal_id"] == "d1"
    assert d["title"] == "chicken breast"
    assert d["sale_price"] == 3.99
    assert d["store_chain"] == "HEB"


# ── ranking constants ─────────────────────────────────────────────────────────

def test_ranking_constants_favour_relevance():
    """COSINE_WEIGHT must be the dominant factor, not SCORE_WEIGHT."""
    from app.services.rag_tools import COSINE_WEIGHT, SCORE_WEIGHT, MIN_COSINE_SIM
    assert COSINE_WEIGHT > SCORE_WEIGHT, (
        "Semantic relevance must outweigh deal score in ranking"
    )
    assert COSINE_WEIGHT + SCORE_WEIGHT == pytest_approx(1.0, abs=0.001), (
        "Weights should sum to 1.0"
    )
    # Low catch-all threshold; LLM does final relevance filtering.
    # The real boundary is validated in test_rag_embedding_quality.py using the actual model.
    assert MIN_COSINE_SIM >= 0.05, "Threshold should at least filter zero-similarity noise"


def pytest_approx(value, abs=1e-6):
    """Tiny inline approx helper so we don't need to import pytest here."""
    class _Approx:
        def __eq__(self, other):
            return math.isclose(other, value, abs_tol=abs)
    return _Approx()


# ── relevance beats deal_score ────────────────────────────────────────────────

def test_high_relevance_beats_high_deal_score():
    """
    A modestly-priced but highly relevant item must rank above a high-scoring
    but weakly related item.

    This is the exact bug that caused 'dental' → duck breast / cola results:
    food items with deal_score=90 were beating dental products with lower scores.
    """
    from app.services.rag_tools import COSINE_WEIGHT, SCORE_WEIGHT

    query_vec = _unit_vec(seed=0)

    # Dental product: high cosine similarity (0.45), low deal score (15)
    dental_sim = 0.45
    dental_score = 15.0
    dental_combined = dental_sim * COSINE_WEIGHT + (dental_score / 100.0) * SCORE_WEIGHT

    # Duck breast: low cosine similarity (0.18), high deal score (92)
    duck_sim = 0.18
    duck_score = 92.0
    duck_combined = duck_sim * COSINE_WEIGHT + (duck_score / 100.0) * SCORE_WEIGHT

    assert dental_combined > duck_combined, (
        f"Dental product (sim={dental_sim}, score={dental_score}) ranked "
        f"{dental_combined:.3f} but duck breast (sim={duck_sim}, score={duck_score}) "
        f"ranked {duck_combined:.3f} — relevance should win"
    )


def test_old_buggy_weights_would_have_failed():
    """Confirm the OLD 0.6/0.4 formula DID produce wrong ranking (regression proof)."""
    dental_combined_old = 0.45 * 0.6 + (15.0 / 100.0) * 0.4   # = 0.33
    duck_combined_old   = 0.18 * 0.6 + (92.0 / 100.0) * 0.4   # = 0.476
    assert duck_combined_old > dental_combined_old, (
        "This test confirms the old 0.6/0.4 formula was broken — "
        "duck breast outranked dental products"
    )


# ── cosine threshold ──────────────────────────────────────────────────────────

def test_threshold_filters_low_similarity_items():
    """Items whose cosine sim to the query is below MIN_COSINE_SIM are excluded."""
    from app.services.rag_tools import semantic_search, MIN_COSINE_SIM, _build_search_intent

    query_vec = _unit_vec(seed=99)

    # Item just ABOVE threshold — should pass
    above_emb = _vec_with_cosine_sim(query_vec, MIN_COSINE_SIM + 0.05)
    # Item just BELOW threshold — should be filtered
    below_emb = _vec_with_cosine_sim(query_vec, MIN_COSINE_SIM - 0.05)

    above_deal = _make_mock_deal("above", "toothpaste", deal_score=10.0, embedding=above_emb)
    below_deal = _make_mock_deal("below", "duck breast", deal_score=95.0, embedding=below_emb)

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [above_deal, below_deal]
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.rag_tools.embed", return_value=query_vec):
        result = asyncio.run(semantic_search("dental", db))

    assert result["success"] is True
    returned_ids = [d["deal_id"] for d in result["data"]]
    assert "above" in returned_ids, "Item above threshold should be returned"
    assert "below" not in returned_ids, (
        "Item below MIN_COSINE_SIM should be filtered even if it has a high deal_score"
    )


def test_all_below_threshold_triggers_ilike_fallback():
    """When every candidate is below MIN_COSINE_SIM, fall back to keyword search."""
    from app.services.rag_tools import semantic_search, MIN_COSINE_SIM, _build_search_intent

    query_vec = _unit_vec(seed=7)
    low_emb = _vec_with_cosine_sim(query_vec, MIN_COSINE_SIM - 0.05)
    bad_deal = _make_mock_deal("noise", "duck breast", deal_score=90.0, embedding=low_emb)

    dental_deal = _make_mock_deal("dental1", "dental floss", deal_score=40.0)

    intent_query_count = len(_build_search_intent("dental floss").semantic_queries)
    db = AsyncMock()
    vector_result = MagicMock()
    vector_result.scalars.return_value.all.return_value = [bad_deal]
    ilike_result = MagicMock()
    ilike_result.scalars.return_value.all.return_value = [dental_deal]
    db.execute = AsyncMock(side_effect=[*([vector_result] * intent_query_count), ilike_result])

    with patch("app.services.rag_tools.embed", return_value=query_vec):
        result = asyncio.run(semantic_search("dental floss", db))

    assert result["success"] is True
    assert result.get("fallback") is True
    assert result["data"][0]["deal_id"] == "dental1"


# ── fallback on empty pgvector ────────────────────────────────────────────────

def test_semantic_search_fallback_on_empty_pgvector():
    """If pgvector returns 0 results, falls back to ILIKE and returns success=True."""
    from app.services.rag_tools import semantic_search

    db = AsyncMock()
    deal = _make_mock_deal()
    empty_result = MagicMock()
    empty_result.scalars.return_value.all.return_value = []
    ilike_result = MagicMock()
    ilike_result.scalars.return_value.all.return_value = [deal]
    db.execute = AsyncMock(
        side_effect=lambda stmt: ilike_result if "ilike" in str(stmt).lower() else empty_result
    )

    with patch("app.services.rag_tools.embed", return_value=_unit_vec()):
        result = asyncio.run(semantic_search("chicken breast", db))

    assert result["success"] is True
    assert result["tool"] == "semantic_search"


# ── intent expansion and strict filtering ─────────────────────────────────────

def test_build_search_intent_expands_tooth_cleaning():
    from app.services.rag_tools import _build_search_intent

    intent = _build_search_intent("tooth cleaning")
    assert "toothpaste" in intent.keywords
    assert "toothbrush" in intent.keywords
    assert len(intent.strict_keywords) > 0


def test_build_search_intent_recipe_adds_ingredients():
    from app.services.rag_tools import _build_search_intent

    intent = _build_search_intent("I am making chinese recipe tonight")
    assert "soy sauce" in intent.keywords
    assert "rice" in intent.keywords
    assert "ginger" in intent.keywords


def test_build_search_intent_detects_general_category_query():
    from app.services.rag_tools import _build_search_intent

    intent = _build_search_intent("show me chips deals for movie night")
    assert "snacks" in intent.categories
    assert len(intent.semantic_queries) >= 2


def test_build_search_intent_recipe_without_cuisine_uses_core_categories():
    from app.services.rag_tools import _build_search_intent

    intent = _build_search_intent("I am cooking a recipe tonight")
    assert intent.recipe_mode is True
    assert "produce" in intent.categories
    assert "pantry" in intent.categories


def test_semantic_search_strict_keywords_filter_noise():
    """
    For intent-heavy queries like "tooth cleaning", food products with no lexical
    overlap should be filtered even if embeddings pull them as neighbors.
    """
    from app.services.rag_tools import semantic_search

    query_vec = _unit_vec(seed=11)
    toothpaste = _make_mock_deal(
        "oral1",
        "Colgate Toothpaste",
        category="oral_care",
        deal_score=20.0,
        embedding=_vec_with_cosine_sim(query_vec, 0.55),
    )
    duck = _make_mock_deal(
        "food1",
        "Duck Breast Fillet",
        category="meat",
        deal_score=95.0,
        embedding=_vec_with_cosine_sim(query_vec, 0.50),
    )

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [toothpaste, duck]
    db.execute = AsyncMock(return_value=mock_result)

    with patch("app.services.rag_tools.embed", return_value=query_vec):
        result = asyncio.run(semantic_search("tooth cleaning", db))

    returned_ids = [d["deal_id"] for d in result["data"]]
    assert "oral1" in returned_ids
    assert "food1" not in returned_ids


def test_recipe_query_is_diversified_not_single_ingredient():
    """
    Recipe intent should not return only one repeated ingredient (e.g. all rice).
    It should keep ingredient coverage in the top results.
    """
    from app.services.rag_tools import semantic_search

    query_vec = _unit_vec(seed=21)
    deals = [
        _make_mock_deal("rice1", "Jasmine Rice", category="pantry", deal_score=80.0, embedding=_vec_with_cosine_sim(query_vec, 0.70)),
        _make_mock_deal("rice2", "Basmati Rice", category="pantry", deal_score=79.0, embedding=_vec_with_cosine_sim(query_vec, 0.69)),
        _make_mock_deal("rice3", "Brown Rice", category="pantry", deal_score=78.0, embedding=_vec_with_cosine_sim(query_vec, 0.68)),
        _make_mock_deal("garlic1", "Fresh Garlic Bulbs", category="produce", deal_score=50.0, embedding=_vec_with_cosine_sim(query_vec, 0.55)),
        _make_mock_deal("chicken1", "Boneless Chicken Thighs", category="meat", deal_score=52.0, embedding=_vec_with_cosine_sim(query_vec, 0.54)),
    ]

    db = AsyncMock()
    vector_result = MagicMock()
    vector_result.scalars.return_value.all.return_value = deals
    db.execute = AsyncMock(return_value=vector_result)

    with patch("app.services.rag_tools.embed", return_value=query_vec):
        result = asyncio.run(semantic_search("I am making fried rice recipe", db, limit=4))

    returned_ids = [d["deal_id"] for d in result["data"]]
    rice_count = sum(1 for deal_id in returned_ids if deal_id.startswith("rice"))
    assert rice_count < len(returned_ids), "Recipe results should not be all rice-only items"
    assert "garlic1" in returned_ids or "chicken1" in returned_ids, (
        "Recipe results should include non-rice ingredients like aromatics/protein"
    )


def test_fried_rice_filters_creamy_garlic_pasta_sauce_noise():
    from app.services.rag_tools import semantic_search

    query_vec = _unit_vec(seed=33)
    good = _make_mock_deal(
        "soy1",
        "Low Sodium Soy Sauce",
        category="pantry",
        deal_score=45.0,
        embedding=_vec_with_cosine_sim(query_vec, 0.62),
    )
    bad = _make_mock_deal(
        "pasta1",
        "Prego Creamy Garlic Pasta Sauce",
        category="pantry",
        deal_score=82.0,
        embedding=_vec_with_cosine_sim(query_vec, 0.63),
    )

    db = AsyncMock()
    vector_result = MagicMock()
    vector_result.scalars.return_value.all.return_value = [bad, good]
    db.execute = AsyncMock(return_value=vector_result)

    with patch("app.services.rag_tools.embed", return_value=query_vec):
        result = asyncio.run(semantic_search("want to make fried rice", db, limit=5))

    returned_ids = [d["deal_id"] for d in result["data"]]
    assert "soy1" in returned_ids
    assert "pasta1" not in returned_ids


# ── filter_by_store ───────────────────────────────────────────────────────────

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


# ── add_to_plan ───────────────────────────────────────────────────────────────

def test_add_to_plan_already_in_list():
    from app.services.rag_tools import add_to_plan

    db = AsyncMock()
    deal = _make_mock_deal()
    deal_result = MagicMock()
    deal_result.scalar_one_or_none.return_value = deal
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = MagicMock()  # already exists
    db.execute = AsyncMock(side_effect=[deal_result, existing_result])

    result = asyncio.run(add_to_plan("d1", "user1", db))
    assert result["success"] is True
    assert "Already" in result["message"]


def test_add_to_plan_deal_not_found():
    from app.services.rag_tools import add_to_plan

    db = AsyncMock()
    not_found = MagicMock()
    not_found.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=not_found)

    result = asyncio.run(add_to_plan("bad_id", "user1", db))
    assert result["success"] is False
    assert "not found" in result["error"]

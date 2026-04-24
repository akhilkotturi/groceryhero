"""
Integration tests for RAG embedding quality — uses the REAL sentence-transformers model.

These tests catch the class of bug where mocked unit tests pass but real embedding
behavior causes wrong results (e.g. 'dental' returning duck breast, cola, chips).

Run with:  pytest tests/test_rag_embedding_quality.py -v
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import numpy as np


def _sim(query_emb: list[float], text: str) -> float:
    from app.services.embeddings import embed
    return float(np.dot(np.array(query_emb), np.array(embed(text))))


# ── threshold contract ────────────────────────────────────────────────────────

def test_min_cosine_sim_constant_is_defined_and_sensible():
    from app.services.rag_tools import MIN_COSINE_SIM
    assert 0.05 <= MIN_COSINE_SIM <= 0.40, (
        f"MIN_COSINE_SIM={MIN_COSINE_SIM} is outside the sensible range 0.05–0.40"
    )


# ── dental query ──────────────────────────────────────────────────────────────

def test_dental_products_score_above_threshold():
    """All common dental/oral-care products must score above MIN_COSINE_SIM for 'dental'."""
    from app.services.embeddings import embed
    from app.services.rag_tools import MIN_COSINE_SIM

    q = embed("dental")
    dental_products = [
        "Oral-B Satin Floss oral_care Oral-B mint waxed 40m",
        "Colgate Total Toothpaste oral_care Colgate whitening 6oz",
        "Listerine Antiseptic Mouthwash oral_care Listerine 500ml",
        "Oral-B CrossAction Toothbrush household Oral-B soft",
        "Crest 3D Whitestrips household Crest whitening",
        # Minimal embed texts (no category) — worst case
        "Colgate Toothpaste",
        "Oral-B Toothbrush",
        "dental floss",
        "Listerine Mouthwash",
    ]
    for text in dental_products:
        s = _sim(q, text)
        assert s >= MIN_COSINE_SIM, (
            f"Dental product '{text}' has sim={s:.4f} < MIN_COSINE_SIM={MIN_COSINE_SIM}. "
            "Dental results would be filtered out."
        )


def test_duck_breast_and_soda_score_below_dental_floor():
    """
    The specific items the user reported receiving for 'dental' (duck breast, cola, chips)
    must score meaningfully lower than the worst dental product.
    This is the regression test for the bug that was reported.
    """
    from app.services.embeddings import embed

    q = embed("dental")

    # Worst-case dental product (minimal embed text, no category)
    worst_dental_sim = min(
        _sim(q, t) for t in [
            "Crest 3D Whitestrips household Crest",
            "Colgate Toothpaste",
            "Oral-B Toothbrush",
            "Listerine Mouthwash",
        ]
    )

    false_positives = {
        "Duck Breast Fillet meat fresh per lb": _sim(q, "Duck Breast Fillet meat fresh per lb"),
        "Coca-Cola Classic beverages 12pk": _sim(q, "Coca-Cola Classic beverages 12pk"),
        "Lay's Potato Chips snacks original": _sim(q, "Lay's Potato Chips snacks original"),
        "Sprite Lemon Lime Soda beverages": _sim(q, "Sprite Lemon Lime Soda beverages"),
        "Planters Peanuts snacks salted": _sim(q, "Planters Peanuts snacks salted"),
    }

    print(f"\n  Worst dental product sim: {worst_dental_sim:.4f}")
    for label, s in false_positives.items():
        print(f"  {label}: {s:.4f}")

    for label, s in false_positives.items():
        assert s < worst_dental_sim, (
            f"'{label}' (sim={s:.4f}) scored >= worst dental product (sim={worst_dental_sim:.4f}). "
            "Food item would appear in dental results."
        )


def test_dental_products_rank_above_food_after_reranking():
    """End-to-end ranking: dental items must outrank food items using actual weights."""
    from app.services.embeddings import embed
    from app.services.rag_tools import COSINE_WEIGHT, SCORE_WEIGHT

    q = np.array(embed("dental"))

    def combined_score(text: str, deal_score: float) -> float:
        sim = float(np.dot(q, np.array(embed(text))))
        return sim * COSINE_WEIGHT + (deal_score / 100.0) * SCORE_WEIGHT

    # Dental products with modest deal scores
    dental_scores = [
        combined_score("Colgate Total Toothpaste oral_care Colgate", 25.0),
        combined_score("Oral-B Pro Toothbrush household Oral-B", 30.0),
        combined_score("dental floss", 15.0),
    ]

    # Food items with HIGH deal scores (the scenario that caused the bug)
    food_scores = [
        combined_score("Duck Breast Fillet meat fresh per lb", 92.0),
        combined_score("Coca-Cola Classic beverages 12pk", 88.0),
        combined_score("Lay's Potato Chips snacks original", 85.0),
    ]

    worst_dental = min(dental_scores)
    best_food = max(food_scores)

    assert worst_dental > best_food, (
        f"Worst dental score ({worst_dental:.4f}) <= best food score ({best_food:.4f}). "
        f"High deal_score food items are outranking dental products. "
        f"COSINE_WEIGHT={COSINE_WEIGHT}, SCORE_WEIGHT={SCORE_WEIGHT}"
    )


# ── other queries sanity check ────────────────────────────────────────────────

def test_chicken_query_returns_meat_not_dental():
    """'chicken breast' must rank chicken above dental/household products."""
    from app.services.embeddings import embed
    from app.services.rag_tools import COSINE_WEIGHT, SCORE_WEIGHT

    q = np.array(embed("chicken breast"))

    def s(text: str) -> float:
        return float(np.dot(q, np.array(embed(text))))

    chicken_sim = s("Boneless Chicken Breast meat fresh per lb")
    dental_sim = s("Colgate Total Toothpaste oral_care Colgate")

    assert chicken_sim > dental_sim, (
        f"'chicken breast' query: chicken sim={chicken_sim:.4f} should beat dental sim={dental_sim:.4f}"
    )


def test_no_single_threshold_issue_for_common_queries():
    """
    For a set of common grocery queries, relevant products must score above
    MIN_COSINE_SIM so the threshold never silently removes correct results.
    """
    from app.services.embeddings import embed
    from app.services.rag_tools import MIN_COSINE_SIM

    cases = [
        ("milk", "Organic Whole Milk dairy Horizon gallon"),
        ("eggs", "Large Eggs dairy dozen 12ct"),
        ("chicken", "Boneless Chicken Breast meat fresh"),
        ("chips", "Lays Classic Potato Chips snacks"),
        ("dental", "Colgate Total Toothpaste oral_care"),
        ("toothbrush", "Oral-B Pro CrossAction Toothbrush household"),
        ("orange juice", "Tropicana Orange Juice beverages 52oz"),
        ("bread", "Wonder Bread bakery white sandwich"),
    ]

    failures = []
    for query, product_text in cases:
        q = np.array(embed(query))
        sim = float(np.dot(q, np.array(embed(product_text))))
        if sim < MIN_COSINE_SIM:
            failures.append(f"  query='{query}' product='{product_text}' sim={sim:.4f} < {MIN_COSINE_SIM}")

    assert not failures, (
        f"These relevant products would be filtered by MIN_COSINE_SIM={MIN_COSINE_SIM}:\n"
        + "\n".join(failures)
    )

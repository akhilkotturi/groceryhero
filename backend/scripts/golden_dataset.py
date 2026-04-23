"""Recall@8 evaluation for the RAG semantic_search tool against labeled queries.

Run: python scripts/golden_dataset.py
Prints recall@8 score (fraction of queries where ≥1 expected result appears in top 8).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

GOLDEN = [
    {"query": "cheap chicken breast", "expected_categories": ["meat"]},
    {"query": "organic produce on sale", "expected_categories": ["produce"]},
    {"query": "milk dairy deals", "expected_categories": ["dairy"]},
    {"query": "frozen pizza deals", "expected_categories": ["frozen"]},
    {"query": "bread bakery sale", "expected_categories": ["bakery"]},
    {"query": "eggs weekly ad", "expected_categories": ["dairy", "produce"]},
    {"query": "beef ground chuck sale", "expected_categories": ["meat"]},
    {"query": "orange juice drinks sale", "expected_categories": ["beverages"]},
    {"query": "chips snacks discount", "expected_categories": ["snacks"]},
    {"query": "butter spread sale", "expected_categories": ["dairy"]},
]


async def evaluate() -> None:
    from app.db.session import AsyncSessionLocal
    from app.services.rag_tools import semantic_search

    hits = 0
    async with AsyncSessionLocal() as db:
        for item in GOLDEN:
            result = await semantic_search(item["query"], db, limit=8)
            found_categories = {d.get("category", "").lower() for d in result["data"] if d.get("category")}
            expected = {c.lower() for c in item["expected_categories"]}
            hit = bool(found_categories & expected)
            hits += int(hit)
            status = "✓" if hit else "✗"
            print(f"  {status} '{item['query']}' → found categories: {found_categories or '(none)'}")

    recall = hits / len(GOLDEN)
    print(f"\nRecall@8: {hits}/{len(GOLDEN)} = {recall:.0%}")
    if recall < 0.5:
        print("WARNING: Recall below 50% — check that embeddings are populated (run embed_existing_deals.py)")


if __name__ == "__main__":
    asyncio.run(evaluate())

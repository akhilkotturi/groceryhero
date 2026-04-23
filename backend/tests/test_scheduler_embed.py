"""Verify embed_batch integration produces correct output shape."""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_embed_batch_matches_deal_count():
    from app.services.embeddings import embed_batch, build_embed_text
    deals = [
        {"normalized_name": "chicken breast", "category": "meat"},
        {"normalized_name": "whole milk", "category": "dairy"},
        {"raw_title": "bananas", "normalized_name": None},
    ]
    texts = [build_embed_text(d) for d in deals]
    embeddings = asyncio.run(embed_batch(texts))
    assert len(embeddings) == len(deals)
    for emb in embeddings:
        assert len(emb) == 384

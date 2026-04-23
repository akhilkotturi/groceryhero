"""Tests for embeddings service."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_build_embed_text_all_fields():
    from app.services.embeddings import build_embed_text
    deal = {
        "normalized_name": "chicken breast",
        "category": "meat",
        "brand": "Tyson",
        "raw_description": "bone-in skinless",
    }
    result = build_embed_text(deal)
    assert "chicken breast" in result
    assert "meat" in result
    assert "Tyson" in result


def test_build_embed_text_missing_fields():
    from app.services.embeddings import build_embed_text
    deal = {"raw_title": "organic milk", "normalized_name": None}
    result = build_embed_text(deal)
    assert "organic milk" in result
    assert result.strip() != ""


def test_build_embed_text_empty():
    from app.services.embeddings import build_embed_text
    result = build_embed_text({})
    assert result == ""


def test_embed_returns_384_floats():
    from app.services.embeddings import embed
    result = embed("chicken breast on sale")
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)


def test_embed_is_normalized():
    import math
    from app.services.embeddings import embed
    result = embed("organic produce")
    magnitude = math.sqrt(sum(x ** 2 for x in result))
    assert abs(magnitude - 1.0) < 0.01


def test_embed_batch_shape():
    import asyncio
    from app.services.embeddings import embed_batch
    texts = ["chicken", "milk", "eggs"]
    results = asyncio.run(embed_batch(texts))
    assert len(results) == 3
    assert all(len(r) == 384 for r in results)

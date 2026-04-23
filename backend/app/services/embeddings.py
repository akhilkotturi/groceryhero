"""Sentence-transformers embedding service. Model loads once at startup."""
import asyncio
import logging

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        from app.core.config import settings
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
        logger.info("Embedding model loaded: %s", settings.EMBEDDING_MODEL)
    return _model


def build_embed_text(deal: dict) -> str:
    """Build the text string that gets embedded for a deal dict."""
    parts = [
        deal.get("normalized_name") or deal.get("raw_title") or "",
        deal.get("category") or "",
        deal.get("brand") or "",
        deal.get("raw_description") or "",
    ]
    return " ".join(p for p in parts if p).strip()


def embed(text: str) -> list[float]:
    """Embed a single string. Returns a list of 384 floats (normalized)."""
    return _get_model().encode(text, normalize_embeddings=True).tolist()


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings in a thread executor to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    model = _get_model()
    embeddings = await loop.run_in_executor(
        None,
        lambda: model.encode(texts, normalize_embeddings=True, batch_size=64),
    )
    return embeddings.tolist()

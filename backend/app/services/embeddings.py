"""Sentence-transformers embedding service. Model loads once at startup."""
import asyncio
import logging

logger = logging.getLogger(__name__)

# Richer context appended to the embed text per category so that natural-language
# queries ("dental care", "indian food", "gluten free") land close to the right deals
# even when the deal's raw title is short (e.g. "Colgate Total 6oz").
_CATEGORY_CONTEXT: dict[str, str] = {
    "household": (
        "personal care hygiene oral care dental toothpaste toothbrush floss mouthwash whitening "
        "shampoo conditioner body wash soap lotion deodorant razor cleaning detergent bleach "
        "laundry dish paper towels toilet paper trash bags"
    ),
    "produce": "fresh fruits vegetables organic farm garden salad greens",
    "meat": "protein fresh meat poultry seafood fish chicken beef pork",
    "dairy": "dairy milk eggs cheese yogurt butter cream refrigerated",
    "pantry": "grocery dry goods canned food cooking staples spices sauce rice pasta beans lentils",
    "snacks": "snack chips crackers candy popcorn nuts granola bar treat",
    "frozen": "frozen freezer aisle ice cream ready to eat convenience",
    "beverages": "drink juice water soda coffee tea beverage refreshment",
    "bakery": "baked goods bread pastry rolls muffin cake donut",
    "deli": "prepared fresh deli rotisserie ready to eat",
    "pet": "pet food dog cat animal care kibble treats",
}

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
    """Build the text string that gets embedded for a deal dict.

    Appends category-specific synonym context so that natural-language queries
    ("dental care", "organic produce") land close to deals whose raw titles are
    short product names with little semantic signal.
    """
    name = deal.get("normalized_name") or deal.get("raw_title") or ""
    brand = deal.get("brand") or ""
    description = deal.get("raw_description") or ""
    category = deal.get("category") or ""
    category_context = _CATEGORY_CONTEXT.get(category, "")
    parts = [name, brand, description, category_context]
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

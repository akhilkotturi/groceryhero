# RAG Agent Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a natural language "Ask your deals" feature backed by a pgvector RAG pipeline and a Ollama llama3.1 ReAct agent that can call tools (semantic_search, filter_by_store, compare_prices, add_to_plan) and return structured JSON for the frontend to render.

**Architecture:** sentence-transformers embeds deals at ingestion time into a `vector(384)` column on the `deals` table; a ReAct agent loop calls pgvector-backed tools to answer user queries; `POST /api/deals/ask` exposes the agent with Redis caching; `AskBar` + `AskResults` components wire into the existing dashboard browse tab.

**Tech Stack:** sentence-transformers (all-MiniLM-L6-v2), pgvector (postgres extension + python package), Ollama llama3.1 (local), httpx (already installed), pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `docker-compose.yml` | Modify | Swap postgres image to pgvector/pgvector:pg16 |
| `backend/requirements.txt` | Modify | Add sentence-transformers, pgvector |
| `backend/app/core/config.py` | Modify | Add OLLAMA_HOST, EMBEDDING_MODEL, RAG_TOP_K, RAG_MAX_TURNS |
| `backend/app/models/deal.py` | Modify | Add `embedding vector(384)` column |
| `backend/scripts/migrate_add_embedding.py` | Create | One-time SQL migration script |
| `backend/app/services/embeddings.py` | Create | sentence-transformers wrapper, embed/embed_batch/build_embed_text |
| `backend/app/workers/scheduler.py` | Modify | Add embed step after score_batch |
| `backend/scripts/embed_existing_deals.py` | Create | Backfill embeddings for existing deals |
| `backend/app/services/rag_tools.py` | Create | semantic_search, filter_by_store, compare_prices, add_to_plan |
| `backend/app/services/rag.py` | Create | ReAct agent loop, Ollama client, tool dispatch |
| `backend/app/api/routes/deals.py` | Modify | Add POST /api/deals/ask route |
| `backend/app/schemas/deal.py` | Modify | Add AskRequest, AskDealResult, AskResponse schemas |
| `backend/tests/test_embeddings.py` | Create | Unit tests for embeddings service |
| `backend/tests/test_rag_tools.py` | Create | Unit tests for RAG tools |
| `backend/tests/test_rag.py` | Create | Unit tests for agent response parsing |
| `backend/scripts/golden_dataset.py` | Create | Recall@8 evaluation against 10 labeled queries |
| `frontend/types/index.ts` | Modify | Add AskResponse, AskDealResult, AskSuggestedAction types |
| `frontend/lib/api.ts` | Modify | Add askDeals() function |
| `frontend/components/deals/AskBar.tsx` | Create | AI query input with submit/clear |
| `frontend/components/deals/AskResults.tsx` | Create | Renders answer + deal cards + action buttons |
| `frontend/app/dashboard/page.tsx` | Modify | Wire AskBar + AskResults into browse tab |

---

## Task 1: Infrastructure — pgvector image + Python dependencies + config

**Files:**
- Modify: `docker-compose.yml`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/core/config.py`
- Modify: `backend/backend/.env` (add OLLAMA_HOST)

- [ ] **Step 1: Swap postgres docker image**

In `docker-compose.yml`, change line 40:
```yaml
# Before:
image: postgres:16-alpine
# After:
image: pgvector/pgvector:pg16
```

- [ ] **Step 2: Add Python dependencies**

In `backend/requirements.txt`, add after the `# ML` section:
```
sentence-transformers==3.0.1
pgvector==0.3.3
```

Also add after `# AI` section (for tests):
```
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 3: Add config settings**

In `backend/app/core/config.py`, add four fields inside the `Settings` class after `GROQ_API_KEY`:
```python
# RAG / local AI
OLLAMA_HOST: str = "http://localhost:11434"
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
RAG_TOP_K: int = 8
RAG_MAX_TURNS: int = 5
```

- [ ] **Step 4: Add env var**

In `backend/.env`, add:
```
OLLAMA_HOST=http://localhost:11434
```

- [ ] **Step 5: Pull new docker image and restart postgres**

```bash
docker-compose pull postgres
docker-compose up -d postgres
```

Expected: postgres container restarts, logs show "PostgreSQL 16" + pgvector extension available.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml backend/requirements.txt backend/app/core/config.py
git commit -m "feat: add pgvector image, sentence-transformers dep, RAG config"
```

---

## Task 2: DB Migration — pgvector extension + embedding column

**Files:**
- Create: `backend/scripts/migrate_add_embedding.py`
- Modify: `backend/app/models/deal.py`

- [ ] **Step 1: Write migration script**

Create `backend/scripts/migrate_add_embedding.py`:
```python
"""One-time migration: enable pgvector extension and add embedding column to deals."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import asyncpg

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


async def run() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        print("✓ pgvector extension enabled")

        await conn.execute(
            "ALTER TABLE deals ADD COLUMN IF NOT EXISTS embedding vector(384);"
        )
        print("✓ embedding column added to deals table")

        await conn.execute(
            "CREATE INDEX IF NOT EXISTS deals_embedding_ivfflat_idx "
            "ON deals USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
        )
        print("✓ IVFFlat index created (lists=100)")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 2: Run the migration**

```bash
cd backend && python scripts/migrate_add_embedding.py
```

Expected output:
```
✓ pgvector extension enabled
✓ embedding column added to deals table
✓ IVFFlat index created (lists=100)
```

- [ ] **Step 3: Add embedding column to Deal SQLAlchemy model**

In `backend/app/models/deal.py`, add the import at the top after the existing imports:
```python
from pgvector.sqlalchemy import Vector
```

Inside the `Deal` class, add after the `created_at` field (before the `store` relationship):
```python
    # RAG embedding (384-dim all-MiniLM-L6-v2)
    embedding: Mapped[list | None] = mapped_column(Vector(384), nullable=True)
```

- [ ] **Step 4: Verify model loads**

```bash
cd backend && python -c "from app.models.deal import Deal; print('Deal.embedding:', Deal.embedding)"
```

Expected: prints `Deal.embedding: Deal.embedding` without errors.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/migrate_add_embedding.py backend/app/models/deal.py
git commit -m "feat: add pgvector embedding column to Deal model and migration script"
```

---

## Task 3: Embeddings Service

**Files:**
- Create: `backend/app/services/embeddings.py`
- Create: `backend/tests/test_embeddings.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_embeddings.py`:
```python
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
    assert abs(magnitude - 1.0) < 0.01  # normalized embeddings have unit magnitude


def test_embed_batch_shape():
    import asyncio
    from app.services.embeddings import embed_batch
    texts = ["chicken", "milk", "eggs"]
    results = asyncio.run(embed_batch(texts))
    assert len(results) == 3
    assert all(len(r) == 384 for r in results)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_embeddings.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.embeddings'`

- [ ] **Step 3: Implement embeddings service**

Create `backend/app/services/embeddings.py`:
```python
"""Sentence-transformers embedding service. Model loads once at startup."""
import asyncio
import logging
from typing import Any

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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/test_embeddings.py -v
```

Expected: all 6 tests PASS. First run downloads ~90MB model — subsequent runs use cache.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/embeddings.py backend/tests/test_embeddings.py
git commit -m "feat: add embeddings service with sentence-transformers all-MiniLM-L6-v2"
```

---

## Task 4: Add Embed Step to Ingestion Scheduler

**Files:**
- Modify: `backend/app/workers/scheduler.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_scheduler_embed.py`:
```python
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
```

- [ ] **Step 2: Run test to confirm it passes (embeddings already work)**

```bash
cd backend && python -m pytest tests/test_scheduler_embed.py -v
```

Expected: PASS (embeddings service is already implemented).

- [ ] **Step 3: Add embed step to scheduler**

In `backend/app/workers/scheduler.py`, add this import at the top with the other service imports (after `from app.services.scorer import score_batch`):
```python
from app.services.embeddings import embed_batch, build_embed_text
```

In the `ingest_deals_for_zip` function, add the embed step between step 3 (Score) and step 4 (Upsert into DB). Find the line `# 4. Upsert into DB` and insert before it:

```python
    # 3b. Embed deals (run in executor — sentence-transformers is sync)
    try:
        embed_texts = [build_embed_text(d) for d in scored]
        embeddings = await embed_batch(embed_texts)
        for deal_data, emb in zip(scored, embeddings):
            deal_data["embedding"] = emb
        logger.info(f"Embedded {len(embeddings)} deals for {zip_code}")
    except Exception as e:
        logger.warning(f"Embedding failed for {zip_code}: {e} — continuing without embeddings")
```

- [ ] **Step 4: Verify scheduler imports cleanly**

```bash
cd backend && python -c "from app.workers.scheduler import ingest_deals_for_zip; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/scheduler.py backend/tests/test_scheduler_embed.py
git commit -m "feat: embed deals in ingestion pipeline after scoring"
```

---

## Task 5: Backfill Existing Deals

**Files:**
- Create: `backend/scripts/embed_existing_deals.py`

- [ ] **Step 1: Write backfill script**

Create `backend/scripts/embed_existing_deals.py`:
```python
"""Backfill script: generate embeddings for all deals where embedding IS NULL."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../.env"))

import asyncpg
from app.services.embeddings import embed_batch, build_embed_text

DATABASE_URL = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
BATCH_SIZE = 64


async def run() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        rows = await conn.fetch(
            "SELECT id, normalized_name, raw_title, category, brand, raw_description "
            "FROM deals WHERE embedding IS NULL"
        )
        total = len(rows)
        print(f"Found {total} deals to embed")
        if total == 0:
            print("Nothing to do.")
            return

        processed = 0
        for i in range(0, total, BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            texts = [build_embed_text(dict(r)) for r in batch]
            embeddings = await embed_batch(texts)

            for row, emb in zip(batch, embeddings):
                emb_str = "[" + ",".join(f"{x:.8f}" for x in emb) + "]"
                await conn.execute(
                    "UPDATE deals SET embedding = $1::vector WHERE id = $2",
                    emb_str,
                    row["id"],
                )
            processed += len(batch)
            print(f"  {processed}/{total} embedded")

        print("Backfill complete.")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
```

- [ ] **Step 2: Run the backfill**

```bash
cd backend && python scripts/embed_existing_deals.py
```

Expected output (count depends on how many deals are in DB):
```
Found N deals to embed
  64/N embedded
  ...
Backfill complete.
```

- [ ] **Step 3: Verify embeddings stored**

```bash
docker exec groceryhero_postgres psql -U groceryhero -c \
  "SELECT COUNT(*) FROM deals WHERE embedding IS NOT NULL;"
```

Expected: count matches number of deals that had text content to embed.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/embed_existing_deals.py
git commit -m "feat: add backfill script for deal embeddings"
```

---

## Task 6: RAG Tools

**Files:**
- Create: `backend/app/services/rag_tools.py`
- Create: `backend/tests/test_rag_tools.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_rag_tools.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_rag_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.rag_tools'`

- [ ] **Step 3: Implement rag_tools.py**

Create `backend/app/services/rag_tools.py`:
```python
"""Tool implementations for the RAG agent. Each tool returns a consistent dict shape."""
import logging
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from app.models.deal import Deal, Store
from app.models.grocery import GroceryListItem
from app.services.embeddings import embed

logger = logging.getLogger(__name__)

_TOP_K = 8


async def semantic_search(
    query: str,
    db: AsyncSession,
    category: str | None = None,
    store: str | None = None,
    limit: int = _TOP_K,
) -> dict[str, Any]:
    """Embed query → pgvector cosine search over 20 candidates → re-rank → return top-k."""
    try:
        query_emb = embed(query)
    except Exception as e:
        logger.error("Embedding failed: %s", e)
        return {"success": False, "data": [], "count": 0, "tool": "semantic_search", "error": str(e)}

    stmt = (
        select(Deal)
        .join(Store)
        .options(selectinload(Deal.store))
        .where(and_(Deal.is_active == True, Deal.embedding.is_not(None)))
        .order_by(Deal.embedding.cosine_distance(query_emb))
        .limit(20)
    )
    if category:
        stmt = stmt.where(Deal.category.ilike(f"%{category}%"))
    if store:
        stmt = stmt.where(Store.chain.ilike(f"%{store}%"))

    result = await db.execute(stmt)
    candidates = result.scalars().all()

    if not candidates:
        # Fallback: keyword ILIKE search
        fallback_stmt = (
            select(Deal)
            .join(Store)
            .options(selectinload(Deal.store))
            .where(
                and_(
                    Deal.is_active == True,
                    or_(
                        Deal.normalized_name.ilike(f"%{query}%"),
                        Deal.raw_title.ilike(f"%{query}%"),
                    ),
                )
            )
            .limit(limit)
        )
        fb_result = await db.execute(fallback_stmt)
        deals = fb_result.scalars().all()
        return {
            "success": True,
            "data": [_deal_to_dict(d) for d in deals],
            "count": len(deals),
            "tool": "semantic_search",
            "fallback": True,
        }

    # Re-rank: cosine_sim * 0.6 + deal_score * 0.4
    # Embeddings are normalized → dot product = cosine similarity
    q_arr = np.array(query_emb, dtype=np.float32)

    def _score(d: Deal) -> float:
        emb_arr = np.array(d.embedding, dtype=np.float32)
        cosine_sim = float(np.dot(q_arr, emb_arr))
        return cosine_sim * 0.6 + ((d.deal_score or 0.0) / 100.0) * 0.4

    ranked = sorted(candidates, key=_score, reverse=True)[:limit]
    return {
        "success": True,
        "data": [_deal_to_dict(d) for d in ranked],
        "count": len(ranked),
        "tool": "semantic_search",
    }


async def filter_by_store(
    store_name: str,
    db: AsyncSession,
    category: str | None = None,
) -> dict[str, Any]:
    """Return top deals from a specific store chain, sorted by deal_score."""
    stmt = (
        select(Deal)
        .join(Store)
        .options(selectinload(Deal.store))
        .where(and_(Deal.is_active == True, Store.chain.ilike(f"%{store_name}%")))
        .order_by(Deal.deal_score.desc().nullslast())
        .limit(_TOP_K)
    )
    if category:
        stmt = stmt.where(Deal.category.ilike(f"%{category}%"))

    result = await db.execute(stmt)
    deals = result.scalars().all()
    return {"success": True, "data": [_deal_to_dict(d) for d in deals], "count": len(deals), "tool": "filter_by_store"}


async def compare_prices(
    item_name: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Run semantic_search, group by store chain, return lowest price per store."""
    search = await semantic_search(item_name, db, limit=20)
    if not search["success"] or not search["data"]:
        return {"success": False, "data": [], "count": 0, "tool": "compare_prices", "error": "no deals found"}

    by_store: dict[str, dict] = {}
    for deal in search["data"]:
        chain = deal.get("store_chain") or "Unknown"
        price = deal.get("sale_price") or deal.get("unit_price")
        if price is None:
            continue
        if chain not in by_store or price < by_store[chain]["lowest_price"]:
            by_store[chain] = {"store": chain, "lowest_price": price, "deal": deal}

    sorted_stores = sorted(by_store.values(), key=lambda x: x["lowest_price"])
    return {"success": True, "data": sorted_stores, "count": len(sorted_stores), "tool": "compare_prices"}


async def add_to_plan(
    deal_id: str,
    user_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Add deal to grocery_list_items. Idempotent (UniqueConstraint handles duplicates)."""
    deal_result = await db.execute(select(Deal).options(selectinload(Deal.store)).where(Deal.id == deal_id))
    deal = deal_result.scalar_one_or_none()
    if not deal:
        return {"success": False, "tool": "add_to_plan", "error": f"Deal {deal_id} not found"}

    existing = await db.execute(
        select(GroceryListItem).where(
            and_(GroceryListItem.user_id == user_id, GroceryListItem.deal_id == deal_id)
        )
    )
    if existing.scalar_one_or_none():
        return {"success": True, "tool": "add_to_plan", "message": "Already in plan", "deal": _deal_to_dict(deal)}

    item = GroceryListItem(user_id=user_id, deal_id=deal_id)
    db.add(item)
    await db.flush()
    return {"success": True, "tool": "add_to_plan", "message": "Added to plan", "deal": _deal_to_dict(deal)}


def _deal_to_dict(d: Deal) -> dict:
    return {
        "deal_id": d.id,
        "title": d.normalized_name or d.raw_title,
        "category": d.category,
        "brand": d.brand,
        "sale_price": d.sale_price,
        "unit_price": d.unit_price,
        "original_price": d.original_price,
        "discount_pct": d.discount_pct,
        "deal_score": d.deal_score,
        "store_chain": d.store.chain if d.store else None,
        "store_name": d.store.name if d.store else None,
        "image_url": d.image_url,
        "store_id": d.store_id,
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/test_rag_tools.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag_tools.py backend/tests/test_rag_tools.py
git commit -m "feat: add RAG tool implementations (semantic_search, filter_by_store, compare_prices, add_to_plan)"
```

---

## Task 7: ReAct Agent Loop

**Files:**
- Create: `backend/app/services/rag.py`
- Create: `backend/tests/test_rag.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_rag.py`:
```python
"""Unit tests for the ReAct agent — tests response parsing and tool dispatch, mocks Ollama."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_parse_final_response_valid_json():
    from app.services.rag import _parse_final_response
    content = '{"answer": "Best deal is HEB chicken.", "deals": [{"deal_id": "d1", "relevance": "cheap"}], "suggested_actions": []}'
    result = _parse_final_response(content, [], 2)
    assert result["answer"] == "Best deal is HEB chicken."
    assert result["turns"] == 2
    assert result["deals"][0]["deal_id"] == "d1"


def test_parse_final_response_with_surrounding_text():
    from app.services.rag import _parse_final_response
    content = 'Here is my answer: {"answer": "Found it.", "deals": [], "suggested_actions": []} That is all.'
    result = _parse_final_response(content, [], 1)
    assert result["answer"] == "Found it."


def test_parse_final_response_invalid_json_fallback():
    from app.services.rag import _parse_final_response
    result = _parse_final_response("not json at all", [], 3)
    assert "answer" in result
    assert result["turns"] == 3
    assert result["deals"] == []


def test_tool_definitions_have_required_fields():
    from app.services.rag import TOOL_DEFINITIONS
    names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
    assert "semantic_search" in names
    assert "filter_by_store" in names
    assert "compare_prices" in names
    assert "add_to_plan" in names
    for tool in TOOL_DEFINITIONS:
        assert "description" in tool["function"]
        assert "parameters" in tool["function"]


def test_system_prompt_contains_json_schema():
    from app.services.rag import SYSTEM_PROMPT
    assert "answer" in SYSTEM_PROMPT
    assert "deals" in SYSTEM_PROMPT
    assert "suggested_actions" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend && python -m pytest tests/test_rag.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.services.rag'`

- [ ] **Step 3: Implement rag.py**

Create `backend/app/services/rag.py`:
```python
"""ReAct agent loop: Reason→Act→Observe using Ollama llama3.1 with tool calling."""
import json
import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import rag_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a grocery deal assistant for GroceryHero. Help users find the best deals.
You have tools: semantic_search (find deals by concept), filter_by_store (deals at one store),
compare_prices (lowest price per store for one item), add_to_plan (save a deal to user's list).

When you have enough context, respond ONLY with valid JSON matching this exact schema:
{
  "answer": "<1-2 sentence summary explaining what you found and why>",
  "deals": [{"deal_id": "<id>", "relevance": "<why this deal is relevant>"}],
  "actions_taken": [],
  "suggested_actions": [{"label": "<button text>", "action": "add_to_plan", "deal_ids": ["<id>"]}]
}
Call tools first to gather deal data, then respond with the JSON."""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": "Search deals by semantic similarity. Use for concept queries like 'cheap chicken', 'organic produce sale'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query"},
                    "category": {"type": "string", "description": "Category filter: produce, meat, dairy, frozen, bakery, etc."},
                    "store": {"type": "string", "description": "Store name filter: HEB, Kroger, Target, etc."},
                    "limit": {"type": "integer", "description": "Max results to return (default 8)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "filter_by_store",
            "description": "Get the top deals from a specific store chain.",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_name": {"type": "string", "description": "Store chain name, e.g. HEB, Kroger, Target, Walmart"},
                    "category": {"type": "string", "description": "Optional category filter"},
                },
                "required": ["store_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_prices",
            "description": "Compare prices for a specific item across all stores. Returns the lowest price at each store.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Grocery item to compare, e.g. 'chicken breast', 'whole milk'"},
                },
                "required": ["item_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_plan",
            "description": "Add a deal to the user's grocery plan. Only call when the user explicitly asks to add or save a deal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "deal_id": {"type": "string", "description": "The deal_id to add to the plan"},
                },
                "required": ["deal_id"],
            },
        },
    },
]


async def run_agent(query: str, user_id: str, db: AsyncSession) -> dict[str, Any]:
    """Run the ReAct agent for a user query. Returns structured JSON response."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    actions_taken: list[str] = []

    for turn in range(settings.RAG_MAX_TURNS):
        try:
            response = await _ollama_chat(messages)
        except httpx.ConnectError:
            raise RuntimeError("Ollama not reachable — is it running at " + settings.OLLAMA_HOST)
        except Exception as e:
            logger.error("Ollama call failed on turn %d: %s", turn + 1, e)
            break

        msg = response.get("message", {})
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return _parse_final_response(msg.get("content", ""), actions_taken, turn + 1)

        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tool_calls,
        })

        for call in tool_calls:
            fn = call.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            result = await _dispatch_tool(name, args, user_id, db)
            if name == "add_to_plan" and result.get("success"):
                actions_taken.append("added_to_plan")
            messages.append({"role": "tool", "content": json.dumps(result)})

    logger.warning("Agent hit MAX_TURNS=%d for query: %s", settings.RAG_MAX_TURNS, query)
    return {
        "answer": "I found some deals that may match your request.",
        "deals": [],
        "actions_taken": actions_taken,
        "suggested_actions": [],
        "turns": settings.RAG_MAX_TURNS,
    }


async def _ollama_chat(messages: list[dict]) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{settings.OLLAMA_HOST}/api/chat",
            json={
                "model": "llama3.1",
                "messages": messages,
                "tools": TOOL_DEFINITIONS,
                "stream": False,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _dispatch_tool(name: str, args: dict, user_id: str, db: AsyncSession) -> dict:
    if name == "semantic_search":
        return await rag_tools.semantic_search(
            query=args["query"], db=db,
            category=args.get("category"), store=args.get("store"),
            limit=args.get("limit", settings.RAG_TOP_K),
        )
    if name == "filter_by_store":
        return await rag_tools.filter_by_store(
            store_name=args["store_name"], db=db, category=args.get("category"),
        )
    if name == "compare_prices":
        return await rag_tools.compare_prices(item_name=args["item_name"], db=db)
    if name == "add_to_plan":
        return await rag_tools.add_to_plan(deal_id=args["deal_id"], user_id=user_id, db=db)
    return {"success": False, "error": f"Unknown tool: {name}", "tool": name}


def _parse_final_response(content: str, actions_taken: list[str], turns: int) -> dict:
    """Extract JSON from LLM content, with fallback for malformed responses."""
    start = content.find("{")
    end = content.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            parsed = json.loads(content[start:end])
            parsed.setdefault("deals", [])
            parsed.setdefault("actions_taken", actions_taken)
            parsed.setdefault("suggested_actions", [])
            parsed["turns"] = turns
            return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {
        "answer": content or "I found some relevant deals.",
        "deals": [],
        "actions_taken": actions_taken,
        "suggested_actions": [],
        "turns": turns,
    }
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend && python -m pytest tests/test_rag.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/rag.py backend/tests/test_rag.py
git commit -m "feat: add ReAct agent loop with Ollama llama3.1 tool calling"
```

---

## Task 8: API Route — POST /api/deals/ask

**Files:**
- Modify: `backend/app/schemas/deal.py`
- Modify: `backend/app/api/routes/deals.py`

- [ ] **Step 1: Add request/response schemas**

In `backend/app/schemas/deal.py`, add at the bottom after `SearchResponse`:
```python

# ── RAG Ask ─────────────────────────────────────────────────────────────────

class AskRequest(BaseModel):
    query: str


class AskDealResult(BaseModel):
    deal_id: str
    deal: Optional[DealOut] = None
    relevance: str = ""


class AskResponse(BaseModel):
    answer: str
    deals: list[AskDealResult]
    actions_taken: list[str]
    suggested_actions: list[dict]
    turns: int
```

- [ ] **Step 2: Add the route**

In `backend/app/api/routes/deals.py`, add these imports at the top, after the existing imports:
```python
import hashlib
from app.schemas.deal import AskRequest, AskResponse, AskDealResult
```

Then add this route at the bottom of the file (before or after `get_deal`):
```python
@router.post("/ask", response_model=AskResponse)
async def ask_deals(
    request: AskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"ask:{current_user.id}:{hashlib.md5(request.query.encode()).hexdigest()[:16]}"
    redis = await get_redis()
    cached = await redis.get(cache_key)
    if cached:
        return AskResponse(**json.loads(cached))

    try:
        from app.services.rag import run_agent
        agent_result = await run_agent(request.query, current_user.id, db)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("RAG agent error: %s", e)
        raise HTTPException(status_code=503, detail="Local AI unavailable")

    # Enrich deal references with full DealOut objects
    enriched_deals: list[AskDealResult] = []
    for ref in agent_result.get("deals", []):
        deal_id = ref.get("deal_id", "")
        relevance = ref.get("relevance", "")
        if deal_id:
            deal_row = await db.execute(
                select(Deal).options(selectinload(Deal.store)).where(Deal.id == deal_id)
            )
            deal_obj = deal_row.scalar_one_or_none()
            enriched_deals.append(AskDealResult(
                deal_id=deal_id,
                relevance=relevance,
                deal=DealOut.model_validate(deal_obj) if deal_obj else None,
            ))

    response = AskResponse(
        answer=agent_result.get("answer", ""),
        deals=enriched_deals,
        actions_taken=agent_result.get("actions_taken", []),
        suggested_actions=agent_result.get("suggested_actions", []),
        turns=agent_result.get("turns", 0),
    )

    await redis.setex(cache_key, 300, response.model_dump_json())
    return response
```

Also add `logger = logging.getLogger(__name__)` near the top of `deals.py` if not already present (add after the imports).

- [ ] **Step 3: Verify the route is importable and the app starts**

```bash
cd backend && python -c "from app.api.routes.deals import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Test the route end-to-end with curl (requires Ollama + deals in DB)**

First ensure Ollama is running:
```bash
ollama serve &
ollama pull llama3.1
```

Then test:
```bash
curl -X POST http://localhost:8000/api/deals/ask \
  -H "Content-Type: application/json" \
  -H "Cookie: <auth_cookie>" \
  -d '{"query": "cheap chicken this week"}'
```

Expected: JSON response with `answer`, `deals`, `suggested_actions`, `turns` fields.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/deal.py backend/app/api/routes/deals.py
git commit -m "feat: add POST /api/deals/ask route with Redis caching and deal enrichment"
```

---

## Task 9: Frontend Types + API Function

**Files:**
- Modify: `frontend/types/index.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Add AskResponse types**

In `frontend/types/index.ts`, add at the bottom:
```typescript
// ── RAG Ask ───────────────────────────────────────────────────────────────────

export interface AskDealResult {
  deal_id: string;
  deal?: Deal;
  relevance: string;
}

export interface AskSuggestedAction {
  label: string;
  action: string;
  deal_ids: string[];
}

export interface AskResponse {
  answer: string;
  deals: AskDealResult[];
  actions_taken: string[];
  suggested_actions: AskSuggestedAction[];
  turns: number;
}
```

- [ ] **Step 2: Add askDeals function to api.ts**

In `frontend/lib/api.ts`, add before the `export default api` line:
```typescript
export async function askDeals(query: string): Promise<AskResponse> {
  const { data } = await api.post<AskResponse>("/api/deals/ask", { query });
  return data;
}
```

Also add this import at the top of `api.ts`:
```typescript
import type { AskResponse } from "@/types";
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/types/index.ts frontend/lib/api.ts
git commit -m "feat: add AskResponse types and askDeals API function"
```

---

## Task 10: AskBar Component

**Files:**
- Create: `frontend/components/deals/AskBar.tsx`

- [ ] **Step 1: Create AskBar component**

Create `frontend/components/deals/AskBar.tsx`:
```tsx
"use client";
import { useState } from "react";
import { Sparkles, Loader2, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AskResponse } from "@/types";
import api from "@/lib/api";

interface AskBarProps {
  onResult: (result: AskResponse) => void;
  onClear: () => void;
  hasResult: boolean;
}

export function AskBar({ onResult, onClear, hasResult }: AskBarProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    try {
      const { data } = await api.post<AskResponse>("/api/deals/ask", { query: q });
      onResult(data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(msg ?? "AI unavailable — is Ollama running?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shrink-0 border-b border-[var(--border)] px-3 py-2 bg-[var(--bg-elevated)]">
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <Sparkles size={14} className="text-[var(--green)] shrink-0" />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Ask AI: cheapest chicken, organic deals under $3, what's on sale at HEB…"
          className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none"
        />
        {hasResult && (
          <button
            type="button"
            aria-label="Clear AI results"
            onClick={() => { setQuery(""); onClear(); }}
            className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
          >
            <X size={13} />
          </button>
        )}
        <button
          type="submit"
          disabled={!query.trim() || loading}
          className={cn(
            "shrink-0 flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold transition-colors",
            query.trim() && !loading
              ? "bg-[var(--green)] text-black hover:opacity-90"
              : "bg-[var(--bg-card)] text-[var(--text-muted)] border border-[var(--border)]"
          )}
        >
          {loading ? <Loader2 size={11} className="animate-spin" /> : "Ask"}
        </button>
      </form>
      {error && <p className="mt-1 pl-5 text-xs text-red-400">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/deals/AskBar.tsx
git commit -m "feat: add AskBar component for natural language deal queries"
```

---

## Task 11: AskResults Component

**Files:**
- Create: `frontend/components/deals/AskResults.tsx`

- [ ] **Step 1: Create AskResults component**

Create `frontend/components/deals/AskResults.tsx`:
```tsx
"use client";
import { useState } from "react";
import { Sparkles, Plus, Check } from "lucide-react";
import type { AskResponse, AskSuggestedAction } from "@/types";
import { DealCard } from "./DealCard";
import { useGroceryStore } from "@/lib/grocery-store";

interface AskResultsProps {
  result: AskResponse;
}

export function AskResults({ result }: AskResultsProps) {
  const { addItem } = useGroceryStore();
  const [doneActions, setDoneActions] = useState<Set<number>>(new Set());

  const dealsWithObjects = result.deals.filter((r) => r.deal != null);

  async function handleAction(action: AskSuggestedAction, idx: number) {
    if (action.action === "add_to_plan") {
      const deals = dealsWithObjects
        .filter((r) => action.deal_ids.includes(r.deal_id))
        .map((r) => r.deal!);
      await Promise.allSettled(deals.map((d) => addItem(d)));
      setDoneActions((prev) => new Set(prev).add(idx));
    }
  }

  if (dealsWithObjects.length === 0 && !result.answer) return null;

  return (
    <div className="shrink-0 border-b border-[var(--border)] bg-[var(--bg-elevated)] px-3 py-3 space-y-3">
      {/* Answer */}
      <div className="flex items-start gap-2">
        <Sparkles size={13} className="text-[var(--green)] mt-0.5 shrink-0" />
        <p className="text-sm text-[var(--text-primary)] leading-snug">{result.answer}</p>
      </div>

      {/* Deal cards */}
      {dealsWithObjects.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {dealsWithObjects.map((ref, i) => (
            <DealCard key={ref.deal_id} deal={ref.deal!} index={i} />
          ))}
        </div>
      )}

      {/* Suggested actions */}
      {result.suggested_actions.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {result.suggested_actions.map((action, i) => (
            <button
              key={i}
              onClick={() => handleAction(action, i)}
              disabled={doneActions.has(i)}
              className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold bg-[var(--green)] text-black hover:opacity-90 transition-opacity disabled:opacity-60"
            >
              {doneActions.has(i) ? <Check size={10} strokeWidth={3} /> : <Plus size={10} />}
              {doneActions.has(i) ? "Done!" : action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/components/deals/AskResults.tsx
git commit -m "feat: add AskResults component rendering agent answer, deal cards, action buttons"
```

---

## Task 12: Dashboard Wiring

**Files:**
- Modify: `frontend/app/dashboard/page.tsx`

- [ ] **Step 1: Add imports to dashboard**

In `frontend/app/dashboard/page.tsx`, add to the existing component imports (around line 12–13):
```typescript
import { AskBar } from "@/components/deals/AskBar";
import { AskResults } from "@/components/deals/AskResults";
import type { AskResponse } from "@/types";
```

- [ ] **Step 2: Add askResult state**

In the `DashboardPage` component, add after the `planError` state (around line 84):
```typescript
const [askResult, setAskResult] = useState<AskResponse | null>(null);
```

- [ ] **Step 3: Wire AskBar + AskResults into browse tab**

In the browse tab section (find `{activeTab === "browse" && (`), add `AskBar` and `AskResults` between the category chips section and the deal grid. Find the closing `</>` of the category chips `<div>` block (ends around line 452), and insert after it:

```tsx
              {/* AI Ask bar */}
              <AskBar
                onResult={setAskResult}
                onClear={() => setAskResult(null)}
                hasResult={askResult !== null}
              />

              {/* AI results (shown above deal grid when active) */}
              {askResult && <AskResults result={askResult} />}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Start dev server and manually test the golden path**

```bash
cd frontend && npm run dev
```

1. Open `http://localhost:3000/dashboard`
2. In the Browse tab, find the AskBar below the category chips
3. Type "cheap chicken this week" and click Ask
4. Verify: spinner appears, then `AskResults` renders with answer + deal cards
5. Type a new query — previous results clear
6. If Ollama is running with llama3.1, verify agent returns real deals

- [ ] **Step 6: Commit**

```bash
git add frontend/app/dashboard/page.tsx
git commit -m "feat: wire AskBar and AskResults into dashboard browse tab"
```

---

## Task 13: Golden Dataset Evaluation

**Files:**
- Create: `backend/scripts/golden_dataset.py`

- [ ] **Step 1: Create golden dataset script**

Create `backend/scripts/golden_dataset.py`:
```python
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
```

- [ ] **Step 2: Run the golden dataset evaluation**

```bash
cd backend && python scripts/golden_dataset.py
```

Expected output (exact numbers depend on your DB):
```
  ✓ 'cheap chicken breast' → found categories: {'meat'}
  ✓ 'organic produce on sale' → found categories: {'produce'}
  ...
Recall@8: 7/10 = 70%
```

A recall ≥ 60% is a good baseline. If recall is low, run `scripts/embed_existing_deals.py` first to ensure embeddings are populated.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/golden_dataset.py
git commit -m "feat: add golden dataset recall@8 evaluation for RAG semantic search"
```

---

## Self-Review Notes

- **Task 2 Step 2 dependency:** The migration script must run BEFORE starting the FastAPI app with the updated Deal model (which expects the `embedding` column to exist). Run the migration once against the live DB before `docker-compose up`.
- **Task 5 (backfill) prerequisite:** Must run after Task 2 (migration) and Task 3 (embeddings service). The backfill uses `embed_batch` from the embeddings service.
- **Task 8 Step 4 (curl test):** Requires Ollama to be running locally (`ollama serve`) with `llama3.1` pulled (`ollama pull llama3.1`). The model is ~4.7GB.
- **Task 12 Step 3 (wiring):** The exact line numbers for insertion may differ if the file was edited. Look for `{/* Category chips + sort */}` comment block to find the right insertion point.
- **IVFFlat index caveat:** The index requires at least `lists * 40 = 4000` rows before it becomes effective. For smaller datasets it falls back to a sequential scan automatically.

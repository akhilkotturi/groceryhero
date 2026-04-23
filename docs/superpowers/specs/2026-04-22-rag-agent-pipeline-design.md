# RAG Agent Pipeline — Design Spec
**Date:** 2026-04-22
**Feature:** Natural language grocery deal search with agentic tool-calling
**Model:** sentence-transformers (all-MiniLM-L6-v2) + Ollama llama3.1

---

## 1. Goal

Add a "Ask your deals" interface where users can ask natural language questions about grocery deals. The system retrieves semantically relevant deals via RAG, then runs a ReAct agent loop using a local LLM (Ollama llama3.1) that can call tools to reason across multiple retrieval steps and optionally take actions (e.g., add a deal to the user's grocery plan).

The output is structured JSON — not just a text answer — so the frontend can render deal cards, action buttons, and a summary sentence.

---

## 2. Architecture

```
Frontend
  AskBar.tsx  ──POST /api/deals/ask──►  FastAPI route
                                              │
                                    ┌─────────▼──────────┐
                                    │   RAG Agent Loop    │
                                    │  (services/rag.py)  │
                                    └─────────┬───────────┘
                                              │ calls tools
                      ┌───────────────────────┼───────────────────────┐
                      ▼                       ▼                       ▼
              semantic_search         compare_prices           add_to_plan
          (embed → pgvector)       (aggregate across        (writes to DB)
                                       stores)
                      │
              ┌───────▼────────┐
              │  pgvector DB   │
              │  deals table   │
              │  + embedding   │
              │  column (384d) │
              └────────────────┘
                      ▲
              Ingestion pipeline
         (scheduler → embed → upsert)
```

**New files:**
- `backend/app/services/embeddings.py` — sentence-transformers wrapper
- `backend/app/services/rag.py` — ReAct agent loop + tool registry
- `backend/scripts/embed_existing_deals.py` — one-time backfill
- `frontend/components/deals/AskBar.tsx`
- `frontend/components/deals/AskResults.tsx`

**Modified files:**
- `backend/app/models/deal.py` — add `embedding vector(384)` column
- `backend/app/api/routes/deals.py` — add `POST /api/deals/ask`
- `backend/app/workers/scheduler.py` — add embed step after scoring
- `backend/app/core/config.py` — add `OLLAMA_HOST` setting
- `docker-compose.yml` — swap to `pgvector/pgvector:pg16`
- `frontend/lib/api.ts` — add `askDeals()`

---

## 3. Data Layer

### Migration
```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE deals ADD COLUMN embedding vector(384);
CREATE INDEX ON deals USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Embedding text
```python
def build_embed_text(deal: dict) -> str:
    parts = filter(None, [
        deal.get("normalized_name"),
        deal.get("category"),
        deal.get("brand"),
        deal.get("raw_description"),
    ])
    return " ".join(parts)
```

### Retrieval query
```python
# Fetch 20 candidates via pgvector, then re-rank in Python
candidates = db.query(Deal).order_by(
    Deal.embedding.cosine_distance(query_embedding)
).filter(Deal.is_active == True).limit(20).all()

# Re-rank: cosine similarity * 0.6 + normalized deal_score * 0.4
# pgvector returns cosine_distance; convert to similarity = 1 - distance
ranked = sorted(candidates, key=lambda d: (
    (1 - float(d.embedding.cosine_distance(query_embedding))) * 0.6 +
    (d.deal_score / 100) * 0.4
), reverse=True)[:8]
```

### docker-compose change
```yaml
# Before
image: postgres:16-alpine
# After
image: pgvector/pgvector:pg16
```

---

## 4. Ingestion Pipeline

Add to `workers/scheduler.py` after `score_batch()`:

```python
from app.services.embeddings import embed_batch, build_embed_text

texts = [build_embed_text(d) for d in normalized_deals]
embeddings = await embed_batch(texts)
for deal, emb in zip(normalized_deals, embeddings):
    deal["embedding"] = emb
```

The sentence-transformers model loads once at process startup and stays in memory. Embedding 100 deals takes ~200ms after warm-up.

---

## 5. ReAct Agent Loop

**`services/rag.py`** implements a Reason→Act→Observe loop:

```
Turn 1: LLM reasons → calls semantic_search("chicken breast deals")
Turn 2: LLM sees results → calls compare_prices("chicken breast")
Turn 3: LLM has enough context → returns structured final answer
```

Loop cap: `MAX_TURNS = 5`. If cap is hit, return whatever deals were retrieved.

**System prompt skeleton:**
```
You are a grocery deal assistant. You have tools to search deals, compare prices 
across stores, and add deals to the user's grocery plan. Answer in 1-2 sentences 
and explain why each deal is relevant. Always respond with valid JSON matching 
the response schema.
```

**Final response schema:**
```json
{
  "answer": "string — 1-2 sentence summary",
  "deals": [{"deal_id": "...", "relevance": "..."}],
  "actions_taken": ["add_to_plan"],
  "suggested_actions": [
    {"label": "Add all to plan", "action": "add_to_plan", "deal_ids": [...]}
  ]
}
```

**Ollama call:**
```python
response = httpx.post(
    f"{settings.OLLAMA_HOST}/api/chat",
    json={"model": "llama3.1", "messages": messages, "tools": TOOL_DEFINITIONS, "stream": False}
)
```

---

## 6. Agent Tools

All tools return `{"success": bool, "data": [...], "count": int, "tool": str}`.

### `semantic_search(query, category?, store?, limit?=8)`
Primary RAG retrieval. Embeds `query` → pgvector cosine search → re-ranks by `cosine_sim * 0.6 + deal_score * 0.4`. Falls back to SQL `ILIKE` if pgvector returns 0 results.

### `filter_by_store(store_name, category?)`
SQL filter on `_merchant_name`. Returns active deals for a specific store. Used for "what's on sale at HEB?"

### `compare_prices(item_name)`
Runs `semantic_search` internally, groups by merchant, returns lowest price per store. Used for "where is chicken cheapest?"

### `add_to_plan(deal_id, user_id)`
Writes to the `grocery_list_items` table (`user_id` + `deal_id`). Agent calls this only when user query implies intent to buy. Returns confirmation with the added deal.

---

## 7. API Route

`POST /api/deals/ask` in `api/routes/deals.py`:

- Auth-protected (existing `get_current_user` dependency)
- Redis cache: 5min TTL, key = `f"ask:{user_id}:{hashlib.md5(query.encode()).hexdigest()[:16]}"`
- Request: `{"query": "cheapest chicken this week"}`
- Response: structured JSON from agent (see §5 schema)
- 503 if Ollama is unreachable, with `{"error": "Local AI unavailable"}`

---

## 8. Frontend

### `AskBar.tsx`
Search input that submits `POST /api/deals/ask`. Shows spinner while agent loop runs (typical 2-4s). Clears AskResults on new query.

### `AskResults.tsx`
Renders structured response:
- `answer` — 1-2 sentence summary card
- `deals` — reuses existing `DealCard` component
- `suggested_actions` — rendered as buttons ("Add all to plan", "Compare stores")
- Dismiss button collapses back to normal deal feed

### Dashboard wiring
AskResults slides in above the deal grid when a query is active. No new page/route needed.

### `lib/api.ts`
```typescript
export async function askDeals(query: string): Promise<AskResponse> {
  return apiFetch("/api/deals/ask", { method: "POST", body: { query } });
}
```

---

## 9. Error Handling

| Scenario | Behavior |
|---|---|
| Ollama not running | 503 + `"Local AI unavailable"`, no crash |
| Agent hits MAX_TURNS | Return deals retrieved so far + partial answer |
| pgvector returns 0 results | Fall back to SQL ILIKE keyword search |
| Embedding model not loaded | 503 + log error, skip embedding step in scheduler |
| `add_to_plan` fails | Return error in `actions_taken`, do not crash agent |

---

## 10. Testing

**`scripts/golden_dataset.py`** — 10 hand-labeled query/expected_deals pairs:
```python
GOLDEN = [
    {"query": "cheap chicken this week", "expected_stores": ["HEB", "Kroger"]},
    {"query": "organic produce deals", "expected_categories": ["produce"]},
    ...
]
```

Run with `python scripts/golden_dataset.py` — prints recall@8 score.

---

## 11. Config

```python
# core/config.py additions
OLLAMA_HOST: str = "http://localhost:11434"
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
RAG_TOP_K: int = 8
RAG_MAX_TURNS: int = 5
```

```env
# .env additions
OLLAMA_HOST=http://localhost:11434
```

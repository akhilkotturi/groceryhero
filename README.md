# GroceryHero

Centralized weekly deal discovery — aggregates grocery store ads, ranks them with ML, and maps them to your neighborhood.

## Features

- **Multi-store aggregation** — HEB, Walmart, Costco, Target, Kroger, Sam's Club, Indian groceries
- **Ranked deals** — XGBoost scorer surfaces best discounts in your region
- **Deal assistant (RAG)** — Natural language queries with semantic search + LLM summarization
- **Neighborhood mapping** — Mapbox integration shows participating stores near you
- **Secure auth** — JWT + httpOnly cookies, token refresh, Redis blacklist
- **Real-time updates** — APScheduler-based deal ingestion every 4–6 hours
- **UI** — Next.js 15, Tailwind, responsive design

## Quick Start

1. **Clone & setup:**
   ```bash
   git clone https://github.com/akhilkotturi/groceryhero.git
   cd groceryhero
   ```

2. **Start backend services:**
   ```bash
   docker compose up --build
   ```

3. **Start frontend (new terminal):**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. **Open browser:**
   - Frontend: `http://localhost:3000`
   - API docs: `http://localhost:8000/docs`

See **[Local Development](#local-development)** for detailed setup & environment variables.

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js 15, Tailwind, Framer Motion, Mapbox GL JS |
| Backend | FastAPI, SQLAlchemy (async), Pydantic v2 |
| Auth | JWT (access + refresh tokens, httpOnly cookies, Redis blacklist) |
| Database | PostgreSQL (Neon in prod, local Docker in dev) |
| Cache | Redis (Upstash in prod, local Docker in dev) |
| Data | Flipp XHR endpoints, Playwright (HEB) |
| ML | spaCy NLP normalization + XGBoost deal scorer |
| RAG / LLM | Groq (Llama 3.3 70B), on-device embeddings |
| Infra | Docker Compose (dev), Railway + Vercel (prod) |

## Project Structure

```
groceryhero/
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py
│       ├── core/         # config, security, redis, deps
│       ├── db/           # SQLAlchemy session + Base
│       ├── models/       # User, Store, Deal
│       ├── schemas/      # Pydantic schemas
│       ├── api/routes/   # auth, users, deals, stores
│       ├── services/     # flipp.py, scraper_heb.py, normalizer.py, scorer.py
│       └── workers/      # scheduler.py (APScheduler cron)
└── frontend/
    ├── app/
    │   ├── auth/login/   # Login page
    │   ├── dashboard/    # Main deal feed + map
    │   └── globals.css
    ├── components/
    │   ├── deals/        # DealCard
    │   ├── map/          # StoreMap (Mapbox)
    │   └── layout/       # Providers
    ├── lib/              # api.ts (axios + interceptor), store.ts (Zustand), utils.ts
    └── types/            # TypeScript interfaces
```

## Local Development

### Prerequisites
- Docker + Docker Compose
- Node.js 20+
- Python 3.12+

### 1. Start backend services

```bash
cd groceryhero
docker compose up --build
```

This starts:
- FastAPI on `http://localhost:8000`
- PostgreSQL on `localhost:5432`
- Redis on `localhost:6379`
- Playwright worker (deal ingestion scheduler)

### 2. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:3000`

### 3. Environment variables

Backend: copy `backend/.env` and fill in:
- `JWT_SECRET_KEY` — generate with `openssl rand -hex 32`
- `MAPBOX_SECRET_TOKEN` — from mapbox.com (free tier)

Frontend: copy `frontend/.env.local` and fill in:
- `NEXT_PUBLIC_MAPBOX_TOKEN` — your Mapbox **public** token

### 4. Trigger a manual deal ingestion

```bash
# Exec into the API container
docker exec -it groceryhero_api bash

# Run ingestion directly
python -m app.workers.scheduler
```

Or hit the scheduler's startup job (runs automatically in development mode).

## API Endpoints

```
POST /api/auth/register     — Create account
POST /api/auth/login        — Login (sets httpOnly cookies)
POST /api/auth/refresh      — Rotate access token
POST /api/auth/logout       — Blacklist tokens

GET  /api/users/me          — Get current user
PATCH /api/users/me         — Update profile/location

GET  /api/deals/nearby      — Get deals by lat/lng (cached)
GET  /api/deals/categories  — Available categories
GET  /api/deals/{id}        — Single deal

GET  /api/stores/nearby     — Stores by lat/lng
```

## ML Pipeline

**Normalization** (`services/normalizer.py`):
- Regex-based price/quantity extraction from raw scraped text
- Brand detection against known brand list
- Category classification via keyword matching
- spaCy NER for product name cleaning

**Deal Scoring** (`services/scorer.py`):
- Heuristic scorer active immediately (discount %, category weight, price ratio, source reliability)
- XGBoost model trains once you have 1000+ implicit user signals (clicks, list adds)
- Call `train_model(deals, labels)` to upgrade from heuristic to ML scoring

## RAG Pipeline (Deal Assistant)

The RAG (Retrieval-Augmented Generation) pipeline powers natural-language deal queries. Users can ask "show me keto deals" or "ingredients for biryani" and get relevant results.

**Phase 1: Query Classification & Expansion** (`services/rag.py`, `_CLASSIFY_EXPAND_PROMPT`):
- Groq LLM classifies the query type: recipe, cuisine, category, dietary, product, store, or general
- Generates 6–10 specific search terms and categories
- Output: structured JSON with intent type and semantic search queries

**Phase 2: Semantic Search** (`services/rag_tools.py`):
- Embeds the expanded search terms using on-device sentence transformers
- Retrieves top 8 deals via cosine similarity (threshold: 0.12, tuned for recall)
- Combines semantic relevance (0.85 weight) + deal quality score (0.15 weight)
- Applies strict keyword filtering for recipes/products (reduces noise)

**Phase 3: LLM Summarization & Filtering** (`services/rag.py`, `_SUMMARIZE_PROMPT`):
- Groq LLM receives user query + candidate deals
- Applies domain-specific filtering rules (e.g., "dental" queries exclude beverages)
- Returns only genuinely relevant deals + a 1–2 sentence summary
- If no matches remain, explains why in the response

**Example Flow:**
- User: "make tacos"
- Classifier → recipe type, searches: "tortillas", "ground beef", "salsa", "cilantro", "lime", etc.
- Semantic search → finds deals on produce, proteins, pantry staples
- LLM → filters out unrelated items, returns top deals for taco ingredients

Embedding models and LLM requests are cached in Redis to minimize cost and latency.

## Deployment (Production)

```
Vercel    → frontend (next build)
Railway   → backend + worker (Docker)
Neon      → PostgreSQL (free tier)
Upstash   → Redis (free tier)
```

Update `DATABASE_URL` and `REDIS_URL` in Railway environment variables to point to Neon/Upstash.

## Running Tests

```bash
# Backend tests
cd backend
pytest tests/ -v

# Frontend tests (if configured)
cd frontend
npm test
```

## Troubleshooting

| Issue | Solution |
|---|---|
| `connection to localhost:5432 refused` | Ensure `docker compose up` completed. Check `docker ps`. |
| `redis connection failed` | Verify Redis is running: `redis-cli ping` should return `PONG`. |
| `JWT_SECRET_KEY not found` | Create `backend/.env` with `JWT_SECRET_KEY=...` (use `openssl rand -hex 32`). |
| `MAPBOX_SECRET_TOKEN not set` | Get a free token at [mapbox.com](https://mapbox.com), add to both `.env` files. |
| `spaCy model not found` | Run `python -m spacy download en_core_web_sm` in the backend container. |
| `Next.js build fails` | Clear `.next` cache: `rm -rf frontend/.next` and retry. |
| `Deals not appearing in dashboard` | Check scheduler logs: `docker logs groceryhero_worker`. Run manual ingestion (see Local Development step 4). |

## Contributing

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make changes & test locally
3. Commit with clear messages: `git commit -m "feat: add new scraper"`
4. Push & open a PR

## License

MIT

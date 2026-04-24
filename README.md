# GroceryHero

Centralized weekly deal discovery — aggregates grocery store ads, ranks them with ML, and maps them to your neighborhood.

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

## Deployment (Production)

```
Vercel    → frontend (next build)
Railway   → backend + worker (Docker)
Neon      → PostgreSQL (free tier)
Upstash   → Redis (free tier)
```

Update `DATABASE_URL` and `REDIS_URL` in Railway environment variables to point to Neon/Upstash.

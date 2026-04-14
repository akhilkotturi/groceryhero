# GroceryHero UI Overhaul + Search — Design Spec

**Date:** 2026-04-14  
**Status:** Approved  
**Scope:** Full frontend overhaul, new search endpoint, Costco scraper fix, planner simplification

---

## Problem Statement

The current dashboard has accumulated several critical issues:
- No search bar — users cannot look up specific products
- The grocery run planner uses a free-text textarea that fails frequently (Groq false negatives, no deals in DB for typed item names)
- The UI is cluttered: hidden filter panel, cramped 420px left panel, disconnected map
- Costco scraper returns 0 results
- The map is decorative rather than functional in browse mode
- Category and store filters are buried behind a toggle button

---

## Decisions Made

| Question | Decision |
|---|---|
| Overall layout | Split panel — deal list left, map right |
| Search placement | Prominent bar in header (center), store filter chips row below |
| Plan UX | Add deals via "+ Plan" button on cards; Plan tab shows counter + grouped results |
| Map role | Store-picker in browse mode + route visualization in plan mode |
| Search implementation | New backend endpoint (`/api/deals/search`) — queries full DB |

---

## Architecture

### Shell Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ HEADER: Logo │ [Search bar — centered, prominent] │ 📍zip 🛒 ⎋  │
├──────────────────────────────────────────────────────────────────┤
│ STORE CHIPS: Nearby: [HEB 142] [Kroger 87] [Walmart 63] [Target] │
├───────────────────────────┬──────────────────────────────────────┤
│  LEFT PANEL (400px)       │  MAP (flex-1)                        │
│  ┌─────────┬──────────┐   │                                      │
│  │ Browse  │ Plan (2) │   │  Browse mode: store pins w/ counts   │
│  └─────────┴──────────┘   │  Plan mode: Stop 1/2, dimmed others  │
│  [category chips row]     │                                      │
│  [deal grid 2-col]        │                                      │
└───────────────────────────┴──────────────────────────────────────┘
```

### Header
- **Logo** — left, fixed width
- **Search bar** — center, `flex:1`, max-width ~500px, always visible, green border
- **Right cluster** — location pill (click to edit zip), grocery list button (badge count), logout icon
- No filter toggle button — filters are always visible as chips

### Store Chips Row
- Rendered below the header, above the main split
- Populated from `GET /api/stores/nearby` response
- Each chip shows: chain name + deal count (from `deals.length` per store)
- Color-coded dot: green (≥75 avg deal score), yellow (≥40), grey (<40 or 0)
- Clicking a chip sets `selectedStore` state — filters the deal list AND highlights that store on the map
- Clicking the active chip clears the filter
- "All stores" chip always present at left, active by default
- Horizontally scrollable if chips overflow

### Left Panel — Browse Tab

- **Category chips** — always visible below tabs (no hidden filter panel), horizontally scrollable
- **Sort** — single dropdown next to category chips ("Best Deal / Biggest Discount / Lowest Price")
- **Deal grid** — 2-column, unchanged card layout with two changes:
  - "+ Plan" button replaces "+ List" button (adds deal ID to plan Zustand store)
  - Cards already in plan show green border + "✓ Plan" badge instead
- When `selectedStore` is set, list is filtered to that store's deals only; a dismissible banner shows the store name
- When search query is active, list shows search results from `/api/deals/search` instead of the default `/api/deals/nearby` feed

### Left Panel — Plan Tab

- **Tab badge** — shows count of deals currently in the plan (0 = no badge)
- **Summary bar** (shown once at least 1 deal is in plan):
  - "N items · M stores"
  - Est. total (sum of effective prices) and savings
  - "Find Best Stores →" button — triggers `POST /api/planner/plan` with selected deal IDs
- **Store groups** — deals grouped by `deal.store_id`, each group has:
  - Store header: chain initial avatar, name, address, distance, subtotal
  - Item rows: thumbnail, name, deal type badge (BOGO / 2/$5 / etc.), original price, effective price, × remove button
- **Empty state** — "Browse deals and tap + Plan to add items"
- **Map syncs** — when Plan tab is active, map switches to plan mode automatically

### Map Behavior

**Browse mode** (Browse tab active):
- All stores rendered as circular markers
- Marker color = deal score color (green/yellow/orange/grey)
- Marker content = deal count number (or store initial if 0)
- Clicking a marker = same as clicking that store's chip (sets `selectedStore`)
- Active store marker gets bright border + larger size
- Popup on hover: store name, address, deal count

**Plan mode** (Plan tab active, plan has stores):
- Plan stores: large bright markers, "Stop N" label above, glowing box-shadow
- Non-plan stores: 25% opacity, no interaction
- Dashed route line connecting plan stores in visit order (Stop 1 → Stop 2 → ...)
- User location pulse at center

---

## Backend Changes

### 1. New search endpoint

**File:** `backend/app/api/routes/deals.py`

```
GET /api/deals/search
  ?q=chicken          # required, min 2 chars
  &lat=30.27
  &lng=-97.74
  &radius_miles=10    # default 10
  &category=meat      # optional
  &per_page=50        # default 50
```

Implementation:
- Same lat/lng bounding box filter as `/api/deals/nearby`
- `WHERE (normalized_name ILIKE '%q%' OR raw_title ILIKE '%q%')`
- Order by `deal_score DESC NULLS LAST`
- Returns same `DealOut` schema with store eager-loaded
- Returns `{ deals: [...], total: N, query: "chicken" }`

### 2. Planner endpoint simplified

**File:** `backend/app/api/routes/planner.py`

Current: accepts `items: list[str]` (free text), runs Groq semantic matching  
New: accepts `deal_ids: list[str]` (UUIDs of deals already selected by user)

New endpoint contract:
```
POST /api/planner/plan
Body: { deal_ids: ["uuid1", "uuid2", ...], lat: float, lng: float }

Response: {
  store_plans: [
    {
      store: StoreOut,
      matches: [{ deal: DealOut, effective_price: float, deal_type: str, price_note: str }],
      total_price: float,
      total_savings: float,
      item_count: int
    }
  ],
  grand_total: float,
  grand_savings: float
}
```

Logic:
1. Fetch all deals by IDs from DB (with store eager-loaded)
2. For each deal, run `parse_deal()` to compute effective price (handles BOGO, 2/$5, etc.)
3. Group by `store_id`
4. Sort groups by item count desc, then total price asc
5. Return `PlanResponse` — no Groq call, no semantic matching

### 3. Costco scraper fix

**File:** `backend/app/services/scraper_costco.py`

- Add `logger.info` lines at key points to surface why 0 results are returned
- Update DOM selectors to match current costco.com product card structure
- Verify stealth mode is applied correctly
- Add a new admin endpoint `GET /api/admin/scraper-status` that returns last-run result counts per scraper (read from a small in-memory dict populated during ingestion)

---

## Frontend State

### Plan Zustand Store

New file: `frontend/lib/plan-store.ts`

```typescript
interface PlanStore {
  dealIds: string[]           // ordered list of selected deal IDs
  deals: Deal[]               // full Deal objects for display
  addDeal: (deal: Deal) => void
  removeDeal: (dealId: string) => void
  clearPlan: () => void
  isInPlan: (dealId: string) => boolean
}
```

- `dealIds` and `deals` kept in sync
- Not persisted to localStorage (plan is ephemeral — one shopping run)
- `isInPlan(id)` used by DealCard to show "✓ Plan" vs "+ Plan" state

### Search State

Managed in `dashboard/page.tsx`:
- `searchQuery: string` — current input value
- `debouncedQuery: string` — 300ms debounced value (triggers API call)
- When `debouncedQuery.length >= 2`: fetch from `/api/deals/search`
- When empty: fall back to `/api/deals/nearby` feed
- TanStack Query key: `["deals-search", debouncedQuery, location, radiusMiles]`

---

## Files Changed

### New files
- `frontend/lib/plan-store.ts`

### Modified files
- `frontend/app/dashboard/page.tsx` — full rewrite of layout, header, store chips, tabs, search state
- `frontend/components/deals/DealCard.tsx` — "+ Plan" button, plan state styling
- `frontend/components/map/StoreMap.tsx` — store-click callback, plan mode route line
- `backend/app/api/routes/deals.py` — add `/search` route
- `backend/app/api/routes/planner.py` — accept deal IDs instead of text items
- `backend/app/api/routes/admin.py` — add `/scraper-status` route
- `backend/app/services/scraper_costco.py` — fix selectors + add logging

### Unchanged
- Auth routes, user routes, grocery store routes
- Ingestion pipeline, scheduler, normalizer, scorer
- `GroceryList` drawer component
- `DealModal` component
- Database models and migrations
- Docker configuration

---

## Out of Scope

- Mobile / responsive layout (desktop only for now)
- Saved plans / plan history (plan is ephemeral)
- Turn-by-turn navigation (map shows stops, not directions)
- Real-time deal price updates

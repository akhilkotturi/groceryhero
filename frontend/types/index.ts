export interface Store {
  id: string;
  chain: string;
  name: string;
  address: string;
  city: string;
  state: string;
  zip_code: string;
  latitude: number;
  longitude: number;
}

export interface Deal {
  id: string;
  store_id: string;
  store?: Store;
  raw_title: string;
  raw_price?: string;
  normalized_name?: string;
  category?: string;
  brand?: string;
  unit_price?: number;
  original_price?: number;
  sale_price?: number;
  discount_pct?: number;
  quantity?: string;
  deal_score?: number;
  valid_from?: string;
  valid_to?: string;
  image_url?: string;
  source: string;
}

export interface DealsResponse {
  deals: Deal[];
  total: number;
  page: number;
  per_page: number;
}

export interface SearchResponse {
  deals: Deal[];
  total: number;
  query: string;
}

export type SortBy = "deal_score" | "discount_pct" | "sale_price";

// ── Grocery Run Planner ───────────────────────────────────────────────────────

/** One deal in the plan with its computed effective price and deal type. */
export interface PlanMatch {
  deal: Deal;
  effective_price: number | null;
  deal_type: "regular" | "bogo" | "buy_get_free" | "multi_price" | "per_lb" | "per_oz";
  price_note: string | null;
}

/** All deals the user should buy at one store. */
export interface StorePlan {
  store: Store;
  matches: PlanMatch[];
  total_price: number;
  total_savings: number;
  item_count: number;
}

/** Response from POST /api/planner/plan */
export interface PlanResponse {
  store_plans: StorePlan[];
  grand_total: number;
  grand_savings: number;
}

export interface DealsFilters {
  lat: number;
  lng: number;
  radius_miles?: number;
  category?: string;
  page?: number;
  per_page?: number;
  sort_by?: SortBy;
}

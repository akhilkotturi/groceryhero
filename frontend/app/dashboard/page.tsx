"use client";
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  MapPin, LogOut, Zap, ShoppingCart, ListChecks,
  Loader2, Pencil, Check as CheckIcon, X as XIcon,
  Search, Sparkles, LocateFixed,
} from "lucide-react";
import dynamic from "next/dynamic";

import { DealCard } from "@/components/deals/DealCard";
import { GroceryList } from "@/components/deals/GroceryList";
import { DealModal } from "@/components/deals/DealModal";
import { AskResults } from "@/components/deals/AskResults";
import type { AskResponse } from "@/types";
import { useAuthStore } from "@/lib/store";
import { useGroceryStore } from "@/lib/grocery-store";
import { usePlanStore } from "@/lib/plan-store";
import api from "@/lib/api";
import { Deal, Store, SortBy, PlanResponse, StorePlan, PlanMatch } from "@/types";
import { cn } from "@/lib/utils";

const StoreMap = dynamic(
  () => import("@/components/map/StoreMap").then((m) => m.StoreMap),
  { ssr: false, loading: () => <div className="w-full h-full bg-[var(--bg-card)] animate-pulse rounded-[var(--radius-lg)]" /> }
);

const CATEGORIES = ["all", "produce", "meat", "dairy", "bakery", "beverages", "snacks", "frozen", "pantry", "household"];
const SORT_OPTIONS: { label: string; value: SortBy }[] = [
  { label: "Best Deal", value: "deal_score" },
  { label: "Biggest Discount", value: "discount_pct" },
  { label: "Lowest Price", value: "sale_price" },
];

type Tab = "browse" | "plan";

async function geocodeZip(zip: string): Promise<{ lat: number; lng: number } | null> {
  try {
    const res = await fetch(`https://api.zippopotam.us/us/${zip.trim()}`);
    if (!res.ok) return null;
    const data = await res.json();
    const place = data.places?.[0];
    if (!place) return null;
    const lat = parseFloat(place.latitude);
    const lng = parseFloat(place.longitude);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
    return { lat, lng };
  } catch {
    return null;
  }
}

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export default function DashboardPage() {
  const { user, setUser, logout } = useAuthStore();
  const queryClient = useQueryClient();
  const { items: groceryItems, isOpen: groceryOpen, setOpen: setGroceryOpen, modalDeal, closeModal, fetchList } = useGroceryStore();
  const planStore = usePlanStore();

  const [location, setLocation] = useState({ lat: 30.2672, lng: -97.7431 });
  // Tracks the user's actual GPS fix — green dot stays here regardless of map pan.
  const [userGps, setUserGps] = useState<{ lat: number; lng: number } | null>(null);
  // Explicit fly-to target: only updated on GPS success or zip submit, never on pan.
  const [flyToTarget, setFlyToTarget] = useState({ lat: 30.2672, lng: -97.7431 });
  const [locationMode, setLocationMode] = useState<"gps" | "zip">("zip");
  const [locating, setLocating] = useState(false);
  const locationRef = useRef(location);
  useEffect(() => { locationRef.current = location; }, [location]);

  const [displayZip, setDisplayZip] = useState<string>(user?.zip_code ?? "");
  const [zipInput, setZipInput] = useState("");
  const [editingZip, setEditingZip] = useState(false);
  const [zipError, setZipError] = useState(false);
  const [radiusMiles] = useState(10);

  const [activeTab, setActiveTab] = useState<Tab>("browse");
  const [selectedStore, setSelectedStore] = useState<Store | null>(null);
  const [category, setCategory] = useState("all");
  const [sortBy, setSortBy] = useState<SortBy>("deal_score");

  const [searchQuery, setSearchQuery] = useState("");
  const debouncedQuery = useDebounce(searchQuery, 300);

  const [planResult, setPlanResult] = useState<PlanResponse | null>(null);
  const [planLoading, setPlanLoading] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [askResult, setAskResult] = useState<AskResponse | null>(null);
  const [aiMode, setAiMode] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const [flyToKey, setFlyToKey] = useState(0);

  const handleStoreClick = useCallback((s: Store) => setSelectedStore(s), []);

  const applyLocation = useCallback((coords: { lat: number; lng: number }, zip?: string) => {
    setLocation((prev) =>
      prev.lat === coords.lat && prev.lng === coords.lng ? prev : coords
    );
    if (zip) setDisplayZip(zip);
    queryClient.invalidateQueries({ queryKey: ["deals"] });
    queryClient.invalidateQueries({ queryKey: ["stores"] });
  }, [queryClient]);

  const handleMapMoveEnd = useCallback(
    (center: { lat: number; lng: number }) => {
      // Only refetch if the center moved >0.5km — zoom events fire moveend too
      // but don't move the center, so this avoids unnecessary reloads.
      // Uses locationRef (not location in closure) so this callback stays stable
      // and the StoreMap moveend listener never captures a stale version.
      const prev = locationRef.current;
      if (Math.abs(center.lat - prev.lat) > 0.005 || Math.abs(center.lng - prev.lng) > 0.005) {
        applyLocation(center);
      }
    },
    [applyLocation]
  );

  const handleGoToMyLocation = useCallback(() => {
    if (userGps) {
      setFlyToTarget({ ...userGps });
      setFlyToKey((k) => k + 1);
      applyLocation(userGps);
      return;
    }

    if (!navigator.geolocation) return;

    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        setUserGps(coords);
        setFlyToTarget(coords);
        setFlyToKey((k) => k + 1);
        setLocationMode("gps");
        applyLocation(coords);
        setLocating(false);
      },
      () => {
        setLocating(false);
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  }, [applyLocation, userGps]);

  const handleAiAsk = useCallback(async (q: string) => {
    const trimmed = q.trim();
    if (!trimmed || aiLoading) return;
    setAiLoading(true);
    setAiError(null);
    try {
      const { data } = await api.post<AskResponse>("/api/deals/ask", { query: trimmed });
      setAskResult(data);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setAiError(msg ?? "AI search unavailable — try again");
    } finally {
      setAiLoading(false);
    }
  }, [aiLoading]);

  useEffect(() => {
    const init = async () => {
      if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const coords = { lat: pos.coords.latitude, lng: pos.coords.longitude };
            setUserGps(coords);
            setFlyToTarget(coords);
            setLocationMode("gps");
            applyLocation(coords);
          },
          async () => {
            const zipCode = useAuthStore.getState().user?.zip_code;
            if (zipCode) {
              const coords = await geocodeZip(zipCode);
              if (coords) {
                setFlyToTarget(coords);
                applyLocation(coords, zipCode);
              }
            }
          },
          { timeout: 8000 }
        );
      } else if (user?.zip_code) {
        const coords = await geocodeZip(user.zip_code);
        if (coords) {
          setFlyToTarget(coords);
          applyLocation(coords, user.zip_code);
        }
      }
    };
    init();

    // Kick off a background deal refresh on every page load so deals stay current
    const zip = useAuthStore.getState().user?.zip_code;
    if (zip) {
      api.post("/api/admin/ingest", { zip_codes: [zip] }).catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { fetchList(); }, []);

  const handleZipSubmit = async () => {
    const z = zipInput.trim();
    if (!/^\d{5}$/.test(z)) { setZipError(true); return; }
    setZipError(false);
    const coords = await geocodeZip(z);
    if (!coords) { setZipError(true); return; }
    applyLocation(coords, z);
    setFlyToTarget(coords);
    setUserGps(null);
    setLocationMode("zip");
    setEditingZip(false);
    try {
      const { data } = await api.patch("/api/users/me", { zip_code: z });
      setUser(data);
    } catch {
      // Zip applied locally; server persistence failed — non-blocking
      console.warn("Failed to persist zip_code to server");
    }
    try { await api.post("/api/admin/ingest", { zip_codes: [z] }); } catch {}
  };

  // ── Data queries ─────────────────────────────────────────────────────────

  const { data: storesData } = useQuery({
    queryKey: ["stores", location, radiusMiles],
    queryFn: async () => {
      const { data } = await api.get(
        `/api/stores/nearby?lat=${location.lat}&lng=${location.lng}&radius_miles=${radiusMiles}`
      );
      return data as Store[];
    },
    enabled: !!location.lat,
  });
  const stores: Store[] = storesData ?? [];

  const nearbyParams = new URLSearchParams(
    Object.entries({
      lat: String(location.lat),
      lng: String(location.lng),
      radius_miles: String(radiusMiles),
      ...(category !== "all" ? { category } : {}),
      sort_by: sortBy,
      per_page: "40",
    }).map(([k, v]) => [k, v])
  );

  const { data: nearbyData, isLoading: nearbyLoading } = useQuery({
    queryKey: ["deals-nearby", location, radiusMiles, category, sortBy],
    queryFn: async () => {
      const { data } = await api.get(`/api/deals/nearby?${nearbyParams}`);
      return data;
    },
    enabled: !!location.lat && debouncedQuery.length < 2,
  });

  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ["deals-search", debouncedQuery, location, radiusMiles],
    queryFn: async () => {
      const params = new URLSearchParams({
        q: debouncedQuery,
        lat: String(location.lat),
        lng: String(location.lng),
        radius_miles: String(radiusMiles),
        per_page: "50",
      });
      const { data } = await api.get(`/api/deals/search?${params}`);
      return data;
    },
    enabled: debouncedQuery.length >= 2 && !aiMode,
  });

  // In AI mode the input drives the AI call, not the live search
  const isSearching = !aiMode && debouncedQuery.length >= 2;
  const dealsLoading = isSearching ? searchLoading : nearbyLoading;
  const rawDeals: Deal[] = isSearching
    ? (searchData?.deals ?? [])
    : (nearbyData?.deals ?? []);

  const deals = selectedStore
    ? rawDeals.filter((d) => d.store_id === selectedStore.id)
    : rawDeals;

  // Deal counts + avg score per store (from nearby feed, not affected by search)
  const { dealCountByStore, avgScoreByStore } = useMemo(() => {
    const allDeals: Deal[] = nearbyData?.deals ?? [];
    const countMap: Record<string, number> = {};
    const scoreSum: Record<string, number> = {};
    const scoreCount: Record<string, number> = {};
    for (const d of allDeals) {
      countMap[d.store_id] = (countMap[d.store_id] ?? 0) + 1;
      if (d.deal_score != null) {
        scoreSum[d.store_id] = (scoreSum[d.store_id] ?? 0) + d.deal_score;
        scoreCount[d.store_id] = (scoreCount[d.store_id] ?? 0) + 1;
      }
    }
    const avgMap: Record<string, number> = {};
    for (const id of Object.keys(scoreSum)) {
      avgMap[id] = scoreSum[id] / scoreCount[id];
    }
    return { dealCountByStore: countMap, avgScoreByStore: avgMap };
  }, [nearbyData]);

  // ── Plan ─────────────────────────────────────────────────────────────────

  async function handleFindBestStores() {
    if (!planStore.dealIds.length) return;
    setPlanLoading(true);
    setPlanError(null);
    try {
      const { data } = await api.post("/api/planner/plan", {
        deal_ids: planStore.dealIds,
        lat: location.lat,
        lng: location.lng,
      });
      setPlanResult(data as PlanResponse);
    } catch (err: any) {
      setPlanError(err?.response?.data?.detail ?? "Failed to optimize plan.");
    } finally {
      setPlanLoading(false);
    }
  }

  const planDeals = planStore.deals;
  const planStoreIds = useMemo(
    () => new Set(planDeals.map((d) => d.store_id)),
    [planDeals]
  );
  const planStoreCount = planStoreIds.size;
  const planEstTotal = planDeals.reduce((s, d) => s + (d.sale_price ?? d.unit_price ?? 0), 0);

  const planRouteStores: Store[] = useMemo(
    () =>
      planResult
        ? planResult.store_plans.map((sp) => sp.store)
        : stores.filter((s) => planStoreIds.has(s.id)),
    [planResult, stores, planStoreIds]
  );

  return (
    <div className="h-screen w-screen bg-[var(--bg)] flex flex-col overflow-hidden">

      {/* ── HEADER ─────────────────────────────────────────────────────── */}
      <header className="flex items-center gap-4 px-6 py-3 border-b border-[var(--border)] shrink-0">
        <div className="flex items-center gap-2 shrink-0">
          <div className="w-7 h-7 rounded-lg bg-[var(--green)] flex items-center justify-center">
            <Zap size={14} className="text-black" />
          </div>
          <span className="font-bold text-lg" style={{ fontFamily: "Syne, sans-serif" }}>
            GroceryHero
          </span>
        </div>

        {/* Unified search bar */}
        <div className="flex-1 flex justify-center">
          <div className="relative w-full max-w-[500px]">
            {/* Left icon */}
            {aiMode
              ? <Sparkles size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--green)] pointer-events-none" />
              : <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
            }
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                if (aiMode) { setAskResult(null); setAiError(null); }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && aiMode) {
                  e.preventDefault();
                  handleAiAsk(searchQuery);
                }
              }}
              placeholder={aiMode
                ? "Ask AI: cheapest chicken, organic deals under $3…"
                : "Search deals… e.g. chicken, milk, eggs"
              }
              className={cn(
                "w-full pl-9 pr-16 py-2 rounded-xl text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none transition-colors",
                aiMode
                  ? "bg-[var(--green-glow)] border border-[var(--green)] focus:ring-1 focus:ring-[var(--green)]"
                  : "bg-[var(--bg-elevated)] border border-[var(--border)] focus:border-[var(--green)]"
              )}
            />
            {/* Right controls */}
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              {aiLoading && <Loader2 size={13} className="text-[var(--green)] animate-spin" />}
              {searchQuery && !aiLoading && (
                <button
                  aria-label="Clear search"
                  onClick={() => { setSearchQuery(""); setAskResult(null); setAiError(null); }}
                  className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] p-0.5"
                >
                  <XIcon size={13} />
                </button>
              )}
              {/* AI toggle */}
              <button
                aria-label={aiMode ? "Disable AI search" : "Enable AI search"}
                onClick={() => {
                  setAiMode((m) => !m);
                  setAskResult(null);
                  setAiError(null);
                }}
                title={aiMode ? "AI mode on — press Enter to search" : "Switch to AI search"}
                className={cn(
                  "p-1.5 rounded-lg transition-colors",
                  aiMode
                    ? "bg-[var(--green)] text-black"
                    : "text-[var(--text-muted)] hover:text-[var(--green)] hover:bg-[var(--green-glow)]"
                )}
              >
                <Sparkles size={13} />
              </button>
            </div>
          </div>
        </div>

        {/* Right cluster */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center gap-1.5 text-sm text-[var(--text-secondary)]">
            <MapPin size={13} className="text-[var(--green)]" />
            {editingZip ? (
              <form onSubmit={(e) => { e.preventDefault(); handleZipSubmit(); }} className="flex items-center gap-1">
                <input
                  autoFocus
                  value={zipInput}
                  onChange={(e) => { setZipInput(e.target.value); setZipError(false); }}
                  placeholder="zip"
                  maxLength={5}
                  className={cn(
                    "w-16 bg-transparent border-b text-sm text-[var(--text-primary)] outline-none pb-0.5",
                    zipError ? "border-red-400" : "border-[var(--green)]"
                  )}
                />
                <button type="submit" aria-label="Save zip" className="text-[var(--green)] p-0.5">
                  <CheckIcon size={13} strokeWidth={3} />
                </button>
                <button type="button" aria-label="Cancel zip edit" onClick={() => { setEditingZip(false); setZipError(false); }} className="text-[var(--text-muted)] p-0.5">
                  <XIcon size={13} />
                </button>
              </form>
            ) : (
              <button onClick={() => { setZipInput(displayZip); setEditingZip(true); }} className="flex items-center gap-1 group">
                <span>{locationMode === "gps" ? "GPS" : (displayZip || "set zip")}</span>
                <Pencil size={10} className="text-[var(--text-muted)] opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            )}
          </div>

          <button
            onClick={() => setGroceryOpen(!groceryOpen)}
            aria-label="Grocery list"
            className="relative p-1.5 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
          >
            <ShoppingCart size={16} />
            {groceryItems.length > 0 && (
              <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-[var(--green)] text-black text-[10px] font-bold flex items-center justify-center">
                {groceryItems.length}
              </span>
            )}
          </button>

          <button aria-label="Log out" onClick={logout} className="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
            <LogOut size={16} />
          </button>
        </div>
      </header>

      {/* ── STORE CHIPS ROW ─────────────────────────────────────────────── */}
      <div className="shrink-0 border-b border-[var(--border)] px-4 py-2 flex items-center gap-2 overflow-x-auto scrollbar-none">
        <button
          onClick={() => setSelectedStore(null)}
          aria-pressed={!selectedStore}
          className={cn(
            "shrink-0 px-3 py-1 rounded-full text-xs font-medium transition-colors",
            !selectedStore
              ? "bg-[var(--green)] text-black"
              : "bg-[var(--bg-card)] text-[var(--text-secondary)] border border-[var(--border)] hover:border-[var(--text-muted)]"
          )}
        >
          All stores
        </button>

        {stores.map((store) => {
          const count = dealCountByStore[store.id] ?? 0;
          const score = avgScoreByStore[store.id] ?? 0;
          const dotColor = score >= 75 ? "bg-[var(--green)]" : score >= 40 ? "bg-yellow-400" : "bg-[var(--text-muted)]";
          const isSelected = selectedStore?.id === store.id;
          return (
            <button
              key={store.id}
              aria-pressed={isSelected}
              onClick={() => setSelectedStore(isSelected ? null : store)}
              className={cn(
                "shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors",
                isSelected
                  ? "bg-[var(--green-glow)] text-[var(--green)] border border-[var(--green)]"
                  : "bg-[var(--bg-card)] text-[var(--text-secondary)] border border-[var(--border)] hover:border-[var(--text-muted)]"
              )}
            >
              <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", dotColor)} />
              {store.chain}
              {count > 0 && <span className="text-[var(--text-muted)]">{count}</span>}
            </button>
          );
        })}
      </div>

      {/* ── MAIN CONTENT ────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* Left panel */}
        <div className="w-[400px] shrink-0 flex flex-col border-r border-[var(--border)] overflow-hidden">

          {/* Tabs */}
          <div className="flex border-b border-[var(--border)] shrink-0">
            {(["browse", "plan"] as Tab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium transition-colors",
                  activeTab === tab
                    ? "text-[var(--text-primary)] border-b-2 border-[var(--green)] -mb-px"
                    : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                )}
              >
                {tab === "browse" ? "Browse Deals" : "Plan Run"}
                {tab === "plan" && planStore.dealIds.length > 0 && (
                  <span className="bg-[var(--green)] text-black text-[10px] font-bold px-1.5 py-0.5 rounded-full leading-none">
                    {planStore.dealIds.length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* ── BROWSE TAB ────────────────────────────────────────────── */}
          {activeTab === "browse" && (
            <>
              {/* Category chips + sort — always visible */}
              <div className="shrink-0 border-b border-[var(--border)] px-3 py-2 flex flex-col gap-2">
                <div className="flex items-center gap-2 overflow-x-auto scrollbar-none">
                  {CATEGORIES.map((cat) => (
                    <button
                      key={cat}
                      aria-pressed={category === cat}
                      onClick={() => setCategory(cat)}
                      className={cn(
                        "shrink-0 px-2.5 py-0.5 rounded-full text-xs capitalize transition-colors",
                        category === cat
                          ? "bg-[var(--green)] text-black font-semibold"
                          : "bg-[var(--bg-card)] text-[var(--text-secondary)] border border-[var(--border)] hover:border-[var(--text-muted)]"
                      )}
                    >
                      {cat}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-1">
                  {SORT_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      aria-pressed={sortBy === opt.value}
                      onClick={() => setSortBy(opt.value)}
                      className={cn(
                        "px-2.5 py-0.5 rounded-full text-xs transition-colors",
                        sortBy === opt.value
                          ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--text-muted)]"
                          : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Store filter banner */}
              {selectedStore && (
                <div className="px-4 py-2 bg-[var(--green-glow)] border-b border-[var(--border)] flex items-center justify-between shrink-0">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-[var(--green)]" />
                    <span className="text-sm font-medium text-[var(--green)]">{selectedStore.name}</span>
                  </div>
                  <button onClick={() => setSelectedStore(null)} className="text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
                    Show all
                  </button>
                </div>
              )}

              {/* Search active indicator */}
              {isSearching && (
                <div className="px-4 py-1.5 bg-[var(--bg-elevated)] border-b border-[var(--border)] shrink-0">
                  <p className="text-xs text-[var(--text-muted)]">
                    Searching for <span className="text-[var(--text-primary)] font-medium">"{debouncedQuery}"</span>
                    {searchData?.total != null && ` · ${searchData.total} results`}
                  </p>
                </div>
              )}

              {/* Deal grid */}
              <div className="flex-1 overflow-y-auto p-3">
                {aiError && (
                  <div className="mb-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-400">
                    {aiError}
                  </div>
                )}
                {askResult && <AskResults result={askResult} />}

                {dealsLoading ? (
                  <div className="grid grid-cols-2 gap-3">
                    {Array.from({ length: 10 }).map((_, i) => (
                      <div key={i} className="h-56 bg-[var(--bg-card)] rounded-[var(--radius)] animate-pulse" />
                    ))}
                  </div>
                ) : deals.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-full text-center gap-3 py-16">
                    <Search size={32} className="text-[var(--text-muted)]" />
                    <p className="text-[var(--text-secondary)] text-sm">
                      {isSearching ? `No results for "${debouncedQuery}"` : "No deals found nearby"}
                    </p>
                    <p className="text-[var(--text-muted)] text-xs">
                      {isSearching ? "Try a different search term" : "Try increasing your radius or check back Monday"}
                    </p>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    {deals.map((deal, i) => (
                      <DealCard key={deal.id} deal={deal} index={i} />
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          {/* ── PLAN TAB ──────────────────────────────────────────────── */}
          {activeTab === "plan" && (
            <div className="flex-1 flex flex-col overflow-hidden">
              {planStore.dealIds.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center gap-3 px-6 py-12">
                  <ListChecks size={32} className="text-[var(--text-muted)]" />
                  <p className="text-sm text-[var(--text-secondary)]">Your plan is empty</p>
                  <p className="text-xs text-[var(--text-muted)]">Browse deals and tap + Plan to add items to your grocery run</p>
                </div>
              ) : (
                <>
                  {/* Summary bar */}
                  <div className="shrink-0 border-b border-[var(--border)] px-4 py-3 flex items-center justify-between">
                    <div>
                      <p className="text-sm font-bold text-[var(--text-primary)]">
                        {planStore.dealIds.length} item{planStore.dealIds.length !== 1 ? "s" : ""} · {planStoreCount} store{planStoreCount !== 1 ? "s" : ""}
                      </p>
                      <p className="text-xs text-[var(--text-muted)] mt-0.5">
                        Est. total{" "}
                        <span className="text-[var(--green)] font-mono font-bold">${planEstTotal.toFixed(2)}</span>
                        {planResult && planResult.grand_savings > 0 && (
                          <> · saving <span className="text-[var(--green)] font-mono font-bold">${planResult.grand_savings.toFixed(2)}</span></>
                        )}
                      </p>
                    </div>
                    <button
                      onClick={handleFindBestStores}
                      disabled={planLoading}
                      className={cn(
                        "flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold transition-colors",
                        planLoading
                          ? "bg-[var(--bg-elevated)] text-[var(--text-muted)] border border-[var(--border)]"
                          : "bg-[var(--green)] text-black hover:opacity-90"
                      )}
                    >
                      {planLoading && <Loader2 size={12} className="animate-spin" />}
                      {planLoading ? "Planning…" : "Find Best Stores →"}
                    </button>
                  </div>

                  {planError && (
                    <div className="px-4 py-2 text-xs text-red-400 border-b border-[var(--border)] shrink-0">
                      {planError}
                    </div>
                  )}

                  {/* Deal groups */}
                  <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
                    <PlanTabGroups
                      planDeals={planDeals}
                      planResult={planResult}
                      onRemove={(id) => {
                        planStore.removeDeal(id);
                        // Always clear plan result when a deal is removed — it reflects the previous selection
                        if (planResult) setPlanResult(null);
                      }}
                    />
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Map */}
        <div className="flex-1 p-4 relative">
          <StoreMap
            stores={stores}
            deals={rawDeals}
            userLat={userGps?.lat ?? location.lat}
            userLng={userGps?.lng ?? location.lng}
            flyToLat={flyToTarget.lat}
            flyToLng={flyToTarget.lng}
            flyToKey={flyToKey}
            onStoreClick={activeTab === "browse" ? handleStoreClick : undefined}
            onMapMoveEnd={handleMapMoveEnd}
            selectedStoreId={activeTab === "browse" ? (selectedStore?.id ?? null) : null}
            planStoreIds={activeTab === "plan" && planStoreIds.size > 0 ? planStoreIds : undefined}
            planRoute={activeTab === "plan" ? planRouteStores : undefined}
          />
          <button
            onClick={handleGoToMyLocation}
            title="Go to my location"
            aria-label="Go to my location"
            disabled={locating}
            className="absolute bottom-8 right-8 w-9 h-9 rounded-full bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--green)] shadow-lg hover:bg-[var(--bg-card)] hover:border-[var(--green)] transition-colors flex items-center justify-center z-10 disabled:opacity-60 disabled:cursor-not-allowed"
          >
            {locating ? <Loader2 size={15} className="animate-spin" /> : <LocateFixed size={15} />}
          </button>
        </div>
      </div>

      <GroceryList />

      <AnimatePresence>
        {modalDeal && <DealModal deal={modalDeal} onClose={closeModal} />}
      </AnimatePresence>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// PlanTabGroups
// ─────────────────────────────────────────────────────────────────────────────

const DEAL_TYPE_COLORS: Record<string, string> = {
  bogo: "text-[var(--green)] bg-[var(--green-glow)] border-[var(--green)]",
  buy_get_free: "text-[var(--green)] bg-[var(--green-glow)] border-[var(--green)]",
  multi_price: "text-yellow-400 bg-yellow-400/10 border-yellow-400/40",
  per_lb: "text-blue-400 bg-blue-400/10 border-blue-400/40",
  per_oz: "text-blue-400 bg-blue-400/10 border-blue-400/40",
  regular: "",
};

interface PlanTabGroupsProps {
  planDeals: Deal[];
  planResult: PlanResponse | null;
  onRemove: (dealId: string) => void;
}

function PlanTabGroups({ planDeals, planResult, onRemove }: PlanTabGroupsProps) {
  if (planResult) {
    return (
      <>
        {planResult.store_plans.map((sp, i) => (
          <OptimizedStoreGroup key={sp.store.id} plan={sp} stopNumber={i + 1} onRemove={onRemove} />
        ))}
      </>
    );
  }

  // Pre-optimization: group planDeals by store
  const groupMap: Record<string, Deal[]> = {};
  for (const deal of planDeals) {
    groupMap[deal.store_id] ??= [];
    groupMap[deal.store_id].push(deal);
  }

  return (
    <>
      {Object.entries(groupMap).map(([storeId, storeDeals]) => {
        const store = storeDeals[0].store;
        const subtotal = storeDeals.reduce((s, d) => s + (d.sale_price ?? d.unit_price ?? 0), 0);
        return (
          <div key={storeId} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-xl overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-[var(--border)]">
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-[var(--green-glow)] border border-[var(--green)] flex items-center justify-center shrink-0">
                  <span className="text-xs font-bold text-[var(--green)]">
                    {(store?.chain ?? "?")[0].toUpperCase()}
                  </span>
                </div>
                <div>
                  <p className="text-xs font-semibold text-[var(--text-primary)]">{store?.name ?? storeId}</p>
                  {store?.address && <p className="text-[10px] text-[var(--text-muted)]">{store.address}</p>}
                </div>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold text-[var(--green)] font-mono">${subtotal.toFixed(2)}</p>
                <p className="text-[10px] text-[var(--text-muted)]">{storeDeals.length} item{storeDeals.length !== 1 ? "s" : ""}</p>
              </div>
            </div>
            <ul className="divide-y divide-[var(--border)]">
              {storeDeals.map((deal) => (
                <PlanDealRow key={deal.id} deal={deal} onRemove={onRemove} />
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

function OptimizedStoreGroup({ plan, stopNumber, onRemove }: { plan: StorePlan; stopNumber: number; onRemove: (id: string) => void }) {
  return (
    <div className="bg-[var(--bg-card)] border border-[var(--green)]/40 rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2.5 bg-[var(--green-glow)]/20 border-b border-[var(--green)]/30">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-[var(--green-glow)] border border-[var(--green)] flex items-center justify-center shrink-0">
            <span className="text-xs font-bold text-[var(--green)]">{plan.store.chain[0].toUpperCase()}</span>
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <p className="text-xs font-semibold text-[var(--text-primary)]">{plan.store.name}</p>
              <span className="text-[9px] bg-[var(--green)] text-black font-bold px-1.5 py-0.5 rounded-full">Stop {stopNumber}</span>
            </div>
            <p className="text-[10px] text-[var(--text-muted)]">{plan.store.address}</p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-sm font-bold text-[var(--green)] font-mono">${plan.total_price.toFixed(2)}</p>
          <p className="text-[10px] text-[var(--text-muted)]">{plan.item_count} item{plan.item_count !== 1 ? "s" : ""}</p>
        </div>
      </div>
      <ul className="divide-y divide-[var(--border)]">
        {plan.matches.map((match) => (
          <li key={match.deal.id} className="flex items-center gap-2 px-3 py-2.5">
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-[var(--text-primary)] truncate">
                {match.deal.normalized_name ?? match.deal.raw_title}
              </p>
              <div className="flex items-center gap-1.5 mt-0.5">
                {match.deal.original_price && (
                  <span className="text-[10px] text-[var(--text-muted)] line-through font-mono">
                    ${match.deal.original_price.toFixed(2)}
                  </span>
                )}
                {match.price_note && (
                  <span className={cn(
                    "text-[9px] px-1.5 py-0.5 rounded-full border font-medium",
                    DEAL_TYPE_COLORS[match.deal_type] || "text-[var(--text-muted)] border-[var(--border)]"
                  )}>
                    {match.price_note}
                  </span>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <span className="text-sm font-bold text-[var(--green)] font-mono">
                {match.effective_price != null ? `$${match.effective_price.toFixed(2)}` : "See store"}
              </span>
              <button aria-label="Remove from plan" onClick={() => onRemove(match.deal.id)} className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
                <XIcon size={13} />
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PlanDealRow({ deal, onRemove }: { deal: Deal; onRemove: (id: string) => void }) {
  const displayPrice = deal.sale_price ?? deal.unit_price;
  return (
    <li className="flex items-center gap-2 px-3 py-2.5 hover:bg-[var(--bg-elevated)] transition-colors">
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-[var(--text-primary)] truncate">
          {deal.normalized_name ?? deal.raw_title}
        </p>
        {deal.original_price && displayPrice && (
          <span className="text-[10px] text-[var(--text-muted)] line-through font-mono">
            ${deal.original_price.toFixed(2)}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {displayPrice != null ? (
          <span className="text-sm font-bold text-[var(--green)] font-mono">${displayPrice.toFixed(2)}</span>
        ) : (
          <span className="text-xs text-[var(--text-muted)]">See store</span>
        )}
        <button aria-label="Remove from plan" onClick={() => onRemove(deal.id)} className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors">
          <XIcon size={13} />
        </button>
      </div>
    </li>
  );
}

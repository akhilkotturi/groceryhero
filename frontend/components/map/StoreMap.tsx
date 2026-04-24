"use client";
import { useRef, useEffect, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { Store, Deal } from "@/types";

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

interface StoreMapProps {
  stores: Store[];
  deals: Deal[];
  /** User's actual GPS position — where the green dot is placed. */
  userLat: number;
  userLng: number;
  /** Explicit fly-to target (GPS resolved or zip submitted). Map animates here when this changes. */
  flyToLat?: number;
  flyToLng?: number;
  /** Increment this to force a re-fly even when lat/lng haven't changed. */
  flyToKey?: number;
  onStoreClick?: (store: Store) => void;
  onMapMoveEnd?: (center: { lat: number; lng: number }) => void;
  /** Browse mode: the currently selected store (gets bright border + larger circle). */
  selectedStoreId?: string | null;
  /** When provided, these store IDs are highlighted in plan mode; others are dimmed. */
  planStoreIds?: Set<string>;
  /**
   * Ordered list of plan stops.
   * When provided, draws a route line and adds Stop N labels.
   */
  planRoute?: Store[];
}

// ─── helpers ────────────────────────────────────────────────────────────────

function getDealScoreForStore(storeId: string, deals: Deal[]): number {
  const sd = deals.filter((d) => d.store_id === storeId && d.deal_score != null);
  if (!sd.length) return 0;
  return sd.reduce((s, d) => s + (d.deal_score ?? 0), 0) / sd.length;
}

function scoreToColor(score: number): string {
  if (score >= 75) return "#00e676";
  if (score >= 50) return "#ffd600";
  if (score >= 25) return "#ff6d00";
  return "#888899";
}

function buildStoreFeatures(
  stores: Store[],
  deals: Deal[],
  selectedStoreId: string | null | undefined,
  planStoreIds: Set<string> | undefined,
  planRoute: Store[] | undefined,
) {
  const isPlanMode = planStoreIds != null && planStoreIds.size > 0;

  return {
    type: "FeatureCollection" as const,
    features: stores.map((store) => {
      const inPlan = planStoreIds?.has(store.id) ?? false;
      const isDimmed = isPlanMode && !inPlan;
      const isSelected = !isPlanMode && selectedStoreId === store.id;
      const score = getDealScoreForStore(store.id, deals);
      const dealCount = deals.filter((d) => d.store_id === store.id).length;
      const stopIndex = planRoute?.findIndex((s) => s.id === store.id) ?? -1;
      const stopNumber = stopIndex >= 0 ? stopIndex + 1 : -1;

      const color = isPlanMode
        ? inPlan ? "#00e676" : "#444466"
        : isSelected ? "#00e676"
        : scoreToColor(score);

      // Short label for inside the circle: deal count when available, else chain initial
      const label = inPlan
        ? (store.chain[0]?.toUpperCase() ?? "?")
        : dealCount > 0 && dealCount < 100 ? String(dealCount)
        : (store.chain[0]?.toUpperCase() ?? "?");

      const circleSize = (isPlanMode && inPlan) || isSelected ? 22 : 18;

      return {
        type: "Feature" as const,
        geometry: {
          type: "Point" as const,
          coordinates: [store.longitude, store.latitude] as [number, number],
        },
        properties: {
          id: store.id,
          name: store.name ?? store.chain,
          chain: store.chain ?? "",
          address: store.address ?? "",
          dealCount,
          score,
          color,
          label,
          circleSize,
          opacity: isDimmed ? 0.3 : 1.0,
          strokeWidth: (inPlan || isSelected) ? 3 : 2,
          stopNumber,
          stopLabel: stopNumber > 0 ? `Stop ${stopNumber}` : "",
        },
      };
    }),
  };
}

// ─── layer/source IDs ────────────────────────────────────────────────────────

const STORES_SOURCE = "stores";
const CLUSTER_LAYER = "clusters";
const CLUSTER_COUNT_LAYER = "cluster-count";
const STORE_CIRCLE_LAYER = "store-circles";
const STORE_LABEL_LAYER = "store-labels";
const STOP_LABEL_LAYER = "stop-labels";
const ROUTE_SOURCE = "plan-route";
const ROUTE_LAYER = "plan-route-line";

// ─── component ───────────────────────────────────────────────────────────────

export function StoreMap({
  stores,
  deals,
  userLat,
  userLng,
  flyToLat,
  flyToLng,
  flyToKey,
  onStoreClick,
  onMapMoveEnd,
  selectedStoreId,
  planStoreIds,
  planRoute,
}: StoreMapProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const userMarker = useRef<mapboxgl.Marker | null>(null);
  const navControl = useRef<mapboxgl.NavigationControl | null>(null);
  const popup = useRef<mapboxgl.Popup | null>(null);
  const [mapLoadKey, setMapLoadKey] = useState(0);

  const onMapMoveEndRef = useRef(onMapMoveEnd);
  useEffect(() => { onMapMoveEndRef.current = onMapMoveEnd; });
  const onStoreClickRef = useRef(onStoreClick);
  useEffect(() => { onStoreClickRef.current = onStoreClick; });
  // stale-closure-safe ref to stores array for click handlers
  const storesRef = useRef(stores);
  useEffect(() => { storesRef.current = stores; });

  // ── Init map once ──────────────────────────────────────────────────────────
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!mapContainer.current || map.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: [userLng, userLat],
      zoom: 11,
      attributionControl: false,
      renderWorldCopies: false,
    });

    navControl.current = new mapboxgl.NavigationControl({ showCompass: false, visualizePitch: false });
    map.current.addControl(navControl.current, "top-right");

    map.current.on("load", () => {
      setMapLoadKey((k) => k + 1);
      map.current?.resize();

      // ── User location pulse marker (HTML — stays separate from store data) ──
      const el = document.createElement("div");
      el.style.cssText = `
        width: 16px; height: 16px;
        background: #00e676;
        border-radius: 50%;
        border: 2px solid #fff;
        box-shadow: 0 0 0 4px rgba(0,230,118,0.3);
        animation: pulse 2s infinite;
        pointer-events: none;
      `;
      userMarker.current = new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([userLng, userLat])
        .addTo(map.current!);

      // ── Store GeoJSON source with native clustering ──────────────────────
      map.current!.addSource(STORES_SOURCE, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
        cluster: true,
        clusterMaxZoom: 11,   // above zoom 11 individual points appear
        clusterRadius: 50,    // px within which points merge
      });

      // Cluster background circles
      map.current!.addLayer({
        id: CLUSTER_LAYER,
        type: "circle",
        source: STORES_SOURCE,
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "#12121e",
          "circle-radius": [
            "step", ["get", "point_count"],
            20,   // ≤4 stores
            5, 24,
            10, 28,
          ],
          "circle-stroke-color": "#00e676",
          "circle-stroke-width": 2.5,
          "circle-opacity": 0.95,
          "circle-stroke-opacity": 0.9,
        },
      });

      // Cluster count labels
      map.current!.addLayer({
        id: CLUSTER_COUNT_LAYER,
        type: "symbol",
        source: STORES_SOURCE,
        filter: ["has", "point_count"],
        layout: {
          "text-field": "{point_count_abbreviated}",
          "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
          "text-size": 12,
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: { "text-color": "#00e676" },
      });

      // Individual store circles
      map.current!.addLayer({
        id: STORE_CIRCLE_LAYER,
        type: "circle",
        source: STORES_SOURCE,
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-color": "#12121e",
          "circle-radius": ["get", "circleSize"],
          "circle-stroke-color": ["get", "color"],
          "circle-stroke-width": ["get", "strokeWidth"],
          "circle-opacity": ["get", "opacity"],
          "circle-stroke-opacity": ["get", "opacity"],
        },
      });

      // Labels inside individual store circles (deal count or chain initial)
      map.current!.addLayer({
        id: STORE_LABEL_LAYER,
        type: "symbol",
        source: STORES_SOURCE,
        filter: ["!", ["has", "point_count"]],
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
          "text-size": 11,
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: {
          "text-color": ["get", "color"],
          "text-opacity": ["get", "opacity"],
        },
      });

      // Stop-number labels above plan-mode store circles
      map.current!.addLayer({
        id: STOP_LABEL_LAYER,
        type: "symbol",
        source: STORES_SOURCE,
        filter: ["all", ["!", ["has", "point_count"]], [">", ["get", "stopNumber"], 0]],
        layout: {
          "text-field": ["get", "stopLabel"],
          "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
          "text-size": 9,
          "text-offset": [0, -3.0],
          "text-anchor": "center",
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: {
          "text-color": "#00e676",
          "text-halo-color": "#000",
          "text-halo-width": 1.5,
        },
      });

      // ── Route line source + layer ─────────────────────────────────────────
      map.current!.addSource(ROUTE_SOURCE, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.current!.addLayer({
        id: ROUTE_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "#00e676",
          "line-width": 2.5,
          "line-opacity": 0.7,
          "line-dasharray": [4, 3],
        },
      });

      // ── Event handlers ────────────────────────────────────────────────────

      // Click individual store: fire onStoreClick + show popup
      map.current!.on("click", STORE_CIRCLE_LAYER, (e) => {
        const feature = e.features?.[0];
        if (!feature?.properties) return;

        const p = feature.properties as {
          id: string; name: string; address: string;
          dealCount: number; score: number; color: string; chain: string;
        };
        const store = storesRef.current.find((s) => s.id === p.id);
        if (store) onStoreClickRef.current?.(store);

        popup.current?.remove();
        const coords = (feature.geometry as unknown as { coordinates: [number, number] }).coordinates;
        popup.current = new mapboxgl.Popup({
          offset: 30,
          closeButton: false,
          closeOnClick: true,
          maxWidth: "220px",
        })
          .setLngLat(coords)
          .setHTML(`
            <div style="padding:12px 14px;">
              <div style="font-family:Syne,sans-serif;font-size:14px;font-weight:700;color:#f0f0f8;margin-bottom:4px;">
                ${p.name}
              </div>
              <div style="font-size:11px;color:#8888aa;margin-bottom:8px;">${p.address}</div>
              <div style="display:flex;align-items:center;gap:6px;">
                <div style="width:8px;height:8px;border-radius:50%;background:${p.color};flex-shrink:0;"></div>
                <span style="font-size:12px;color:${p.color};font-weight:600;">${p.dealCount} active deal${p.dealCount !== 1 ? "s" : ""}</span>
              </div>
              ${p.score > 0 ? `<div style="font-size:11px;color:#8888aa;margin-top:4px;">Avg score: ${Math.round(p.score)}/100</div>` : ""}
            </div>
          `)
          .addTo(map.current!);
      });

      // Click cluster: zoom in to expand it
      map.current!.on("click", CLUSTER_LAYER, (e) => {
        const features = map.current!.queryRenderedFeatures(e.point, { layers: [CLUSTER_LAYER] });
        if (!features.length) return;
        const clusterId = features[0]?.properties?.cluster_id as number;
        const source = map.current!.getSource(STORES_SOURCE) as mapboxgl.GeoJSONSource;
        source.getClusterExpansionZoom(clusterId, (err, zoom) => {
          if (err || zoom == null) return;
          const coords = (features[0].geometry as unknown as { coordinates: [number, number] }).coordinates;
          map.current!.easeTo({ center: coords as [number, number], zoom: zoom + 0.5 });
        });
      });

      // Pointer cursor on interactive layers
      const canvas = map.current!.getCanvas();
      for (const layer of [STORE_CIRCLE_LAYER, CLUSTER_LAYER]) {
        map.current!.on("mouseenter", layer, () => { canvas.style.cursor = "pointer"; });
        map.current!.on("mouseleave", layer, () => { canvas.style.cursor = ""; });
      }
    });

    map.current.on("moveend", () => {
      const center = map.current?.getCenter();
      if (center) onMapMoveEndRef.current?.({ lat: center.lat, lng: center.lng });
    });

    const ro = new ResizeObserver(() => map.current?.resize());
    ro.observe(mapContainer.current);

    return () => {
      ro.disconnect();
      popup.current?.remove();
      userMarker.current?.remove();
      userMarker.current = null;
      navControl.current = null;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  // ── Keep green dot at real GPS position (separate from search center pan) ──
  useEffect(() => {
    if (!mapLoadKey) return;
    userMarker.current?.setLngLat([userLng, userLat]);
  }, [mapLoadKey, userLat, userLng]);

  // ── Fly to explicit target (GPS fix or zip submit) ────────────────────────
  useEffect(() => {
    if (!mapLoadKey || !map.current || flyToLat == null || flyToLng == null) return;
    map.current.flyTo({ center: [flyToLng, flyToLat], duration: 1200 });
  }, [mapLoadKey, flyToLat, flyToLng, flyToKey]);

  // ── Update store GeoJSON — triggers Mapbox re-cluster automatically ───────
  useEffect(() => {
    if (!mapLoadKey || !map.current) return;
    const source = map.current.getSource(STORES_SOURCE) as mapboxgl.GeoJSONSource | undefined;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    source?.setData(buildStoreFeatures(stores, deals, selectedStoreId, planStoreIds, planRoute) as any);
  }, [mapLoadKey, stores, deals, selectedStoreId, planStoreIds, planRoute]);

  // ── Update route line ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapLoadKey || !map.current) return;
    const source = map.current.getSource(ROUTE_SOURCE) as mapboxgl.GeoJSONSource | undefined;
    if (!source) return;
    if (planRoute && planRoute.length >= 2) {
      source.setData({
        type: "Feature",
        properties: {},
        geometry: {
          type: "LineString",
          coordinates: planRoute.map((s) => [s.longitude, s.latitude]),
        },
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any);
    } else {
      source.setData({ type: "FeatureCollection", features: [] });
    }
  }, [mapLoadKey, planRoute]);

  const radius = "var(--radius-lg)";

  return (
    <>
      <style>{`
        @keyframes pulse {
          0%   { box-shadow: 0 0 0 0   rgba(0,230,118,0.4); }
          70%  { box-shadow: 0 0 0 10px rgba(0,230,118,0);   }
          100% { box-shadow: 0 0 0 0   rgba(0,230,118,0);    }
        }
        .gh-map-canvas .mapboxgl-canvas { border-radius: ${radius}; }
        .mapboxgl-popup-content {
          background: #12121e !important;
          padding: 0 !important;
          border-radius: 10px !important;
          box-shadow: 0 4px 24px rgba(0,0,0,0.6) !important;
          border: 1px solid #2a2a40 !important;
        }
        .mapboxgl-popup-tip { display: none !important; }
      `}</style>
      <div style={{ position: "relative", width: "100%", height: "100%", borderRadius: radius }}>
        <div
          ref={mapContainer}
          className="gh-map-canvas"
          style={{ width: "100%", height: "100%" }}
        />
      </div>
    </>
  );
}

"use client";
import { Deal } from "@/types";
import { motion } from "framer-motion";
import { MapPin, Tag, TrendingDown, Plus, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import Image from "next/image";
import { useState } from "react";
import { useGroceryStore } from "@/lib/grocery-store";
import { usePlanStore } from "@/lib/plan-store";

interface DealCardProps {
  deal: Deal;
  index?: number;
}

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 75
      ? "text-[var(--green)] border-[var(--green)]"
      : score >= 50
      ? "text-[var(--yellow)] border-[var(--yellow)]"
      : "text-[var(--text-secondary)] border-[var(--border)]";

  return (
    <div className={cn("flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-semibold font-mono", color)}>
      <TrendingDown size={10} />
      {score.toFixed(0)}
    </div>
  );
}

export function DealCard({ deal, index = 0 }: DealCardProps) {
  const [imgError, setImgError] = useState(false);
  const { openModal } = useGroceryStore();
  const inPlan = usePlanStore((s) => s.dealIds.includes(deal.id));
  const addDeal = usePlanStore((s) => s.addDeal);
  const removeDeal = usePlanStore((s) => s.removeDeal);
  const displayPrice = deal.sale_price ?? deal.unit_price;
  const hasDiscount = deal.discount_pct && deal.discount_pct > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.04 }}
      className={cn(
        "group relative bg-[var(--bg-card)] border rounded-[var(--radius)] overflow-hidden hover:bg-[var(--bg-elevated)] transition-colors duration-200",
        inPlan
          ? "border-[var(--green)]"
          : "border-[var(--border)] hover:border-[var(--border-subtle)]"
      )}
    >
      {/* Discount ribbon (hidden when in plan to avoid badge overlap) */}
      {hasDiscount && !inPlan && (
        <div className="absolute top-3 left-3 z-10 bg-[var(--green)] text-black text-xs font-bold px-2 py-0.5 rounded-full">
          -{deal.discount_pct?.toFixed(0)}%
        </div>
      )}

      {/* Plan badge (shown when deal is in plan) */}
      {inPlan && (
        <div className="absolute top-3 left-3 z-10 flex items-center gap-1 bg-[var(--green)] text-black text-[10px] font-bold px-2 py-0.5 rounded-full">
          <Check size={9} strokeWidth={3} />
          Plan
        </div>
      )}

      {/* + Plan / ✓ Plan button */}
      <button
        aria-label={inPlan ? "Remove from plan" : "Add to plan"}
        onClick={(e) => {
          e.stopPropagation();
          inPlan ? removeDeal(deal.id) : addDeal(deal);
        }}
        className={cn(
          "absolute top-2 right-2 z-10 w-7 h-7 rounded-full flex items-center justify-center transition-all duration-150 shadow-md",
          inPlan
            ? "bg-[var(--green)] text-black"
            : "bg-[var(--bg-elevated)] text-[var(--text-muted)] opacity-0 group-hover:opacity-100 hover:text-[var(--green)] hover:bg-[var(--bg-card)] border border-[var(--border)]"
        )}
      >
        {inPlan ? <Check size={12} strokeWidth={3} /> : <Plus size={13} />}
      </button>

      {/* Clickable area → opens deal detail modal */}
      <button className="w-full text-left" onClick={() => openModal(deal)}>
        {/* Image */}
        <div className="relative h-36 bg-[var(--bg-elevated)] overflow-hidden">
          {deal.image_url && !imgError ? (
            <Image
              src={deal.image_url}
              alt={deal.normalized_name ?? deal.raw_title}
              fill
              sizes="200px"
              className="object-contain p-4 group-hover:scale-105 transition-transform duration-300"
              onError={() => setImgError(true)}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <Tag size={32} className="text-[var(--text-muted)]" />
            </div>
          )}
        </div>

        {/* Content */}
        <div className="p-3 space-y-2">
          {/* Category + score */}
          <div className="flex items-center justify-between">
            {deal.category && (
              <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-medium">
                {deal.category}
              </span>
            )}
            {deal.deal_score != null && <ScoreBadge score={deal.deal_score} />}
          </div>

          {/* Title */}
          <p className="text-sm font-medium text-[var(--text-primary)] leading-snug line-clamp-2">
            {deal.normalized_name ?? deal.raw_title}
          </p>

          {deal.brand && (
            <p className="text-xs text-[var(--text-muted)]">{deal.brand}</p>
          )}

          {/* Price row */}
          <div className="flex items-end justify-between pt-1">
            <div>
              {displayPrice != null ? (
                <div className="flex items-baseline gap-1.5">
                  <span className="text-lg font-bold text-[var(--green)] font-mono">
                    ${displayPrice.toFixed(2)}
                  </span>
                  {deal.original_price && (
                    <span className="text-xs text-[var(--text-muted)] line-through font-mono">
                      ${deal.original_price.toFixed(2)}
                    </span>
                  )}
                </div>
              ) : (
                <span className="text-sm text-[var(--text-secondary)]">
                  {deal.quantity ?? deal.raw_price ?? "See store"}
                </span>
              )}
              {deal.quantity && displayPrice != null && (
                <p className="text-[11px] text-[var(--text-muted)]">{deal.quantity}</p>
              )}
            </div>

            {deal.store && (
              <div className="flex items-center gap-1 text-[11px] text-[var(--text-muted)]">
                <MapPin size={10} />
                <span>{deal.store.chain}</span>
              </div>
            )}
          </div>
        </div>
      </button>
    </motion.div>
  );
}

"use client";
import { useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import Image from "next/image";
import {
  X, MapPin, Tag, TrendingDown, ShoppingCart, Trash2, Maximize2,
} from "lucide-react";
import { Deal } from "@/types";
import { useGroceryStore } from "@/lib/grocery-store";
import { cn } from "@/lib/utils";

interface DealModalProps {
  deal: Deal;
  onClose: () => void;
}

function PriceBadge({ deal }: { deal: Deal }) {
  const display = deal.sale_price ?? deal.unit_price;
  if (display == null) return null;
  return (
    <div className="flex items-baseline gap-3">
      <span className="text-4xl font-bold text-[var(--green)] font-mono">
        ${display.toFixed(2)}
      </span>
      {deal.original_price && (
        <span className="text-lg text-[var(--text-muted)] line-through font-mono">
          ${deal.original_price.toFixed(2)}
        </span>
      )}
      {deal.discount_pct && deal.discount_pct > 0 && (
        <span className="flex items-center gap-1 px-2.5 py-1 rounded-full bg-[var(--green-glow)] text-[var(--green)] text-sm font-bold border border-[var(--green)]">
          <TrendingDown size={12} />
          {deal.discount_pct.toFixed(0)}% off
        </span>
      )}
    </div>
  );
}

export function DealModal({ deal, onClose }: DealModalProps) {
  const { isInList, addItem, removeItem } = useGroceryStore();
  const inList = isInList(deal.id);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  // Lock body scroll
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center"
      onClick={onClose}
    >
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
      />

      {/* Panel */}
      <motion.div
        initial={{ opacity: 0, y: 40, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 40, scale: 0.97 }}
        transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
        className="relative z-10 w-full sm:max-w-lg max-h-[92dvh] overflow-y-auto bg-[var(--bg-card)] border border-[var(--border)] rounded-t-2xl sm:rounded-2xl shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close + Fullscreen row */}
        <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-3 bg-[var(--bg-card)]/90 backdrop-blur border-b border-[var(--border)]">
          <span className="text-xs text-[var(--text-muted)] uppercase tracking-widest font-medium">
            Deal Details
          </span>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Image */}
        <div className="relative w-full h-64 bg-[var(--bg-elevated)]">
          {deal.image_url ? (
            <Image
              src={deal.image_url}
              alt={deal.normalized_name ?? deal.raw_title}
              fill
              sizes="512px"
              className="object-contain p-6"
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <Tag size={48} className="text-[var(--text-muted)]" />
            </div>
          )}
          {deal.discount_pct && deal.discount_pct > 0 && (
            <div className="absolute top-3 left-3 bg-[var(--green)] text-black text-sm font-bold px-3 py-1 rounded-full">
              -{deal.discount_pct.toFixed(0)}%
            </div>
          )}
        </div>

        {/* Content */}
        <div className="p-5 space-y-5">
          {/* Category */}
          {deal.category && (
            <span className="text-[10px] uppercase tracking-widest text-[var(--text-muted)] font-medium">
              {deal.category}
            </span>
          )}

          {/* Title */}
          <div>
            <h2 className="text-xl font-bold text-[var(--text-primary)] leading-tight" style={{ fontFamily: "Syne, sans-serif" }}>
              {deal.normalized_name ?? deal.raw_title}
            </h2>
            {deal.brand && (
              <p className="mt-1 text-sm text-[var(--text-muted)]">{deal.brand}</p>
            )}
          </div>

          {/* Price */}
          <PriceBadge deal={deal} />

          {/* Quantity */}
          {deal.quantity && (
            <div className="px-3 py-2 bg-[var(--bg-elevated)] rounded-lg text-sm text-[var(--text-secondary)]">
              {deal.quantity}
            </div>
          )}

          {/* Store info */}
          {deal.store && (
            <div className="flex items-start gap-3 pt-1 border-t border-[var(--border)]">
              <div className="w-8 h-8 rounded-lg bg-[var(--bg-elevated)] flex items-center justify-center shrink-0 mt-0.5">
                <MapPin size={14} className="text-[var(--green)]" />
              </div>
              <div>
                <p className="text-sm font-medium text-[var(--text-primary)]">{deal.store.name}</p>
                <p className="text-xs text-[var(--text-muted)]">{deal.store.address}, {deal.store.city}</p>
              </div>
            </div>
          )}

          {/* Validity */}
          {(deal.valid_from || deal.valid_to) && (
            <p className="text-xs text-[var(--text-muted)]">
              Valid{" "}
              {deal.valid_from && new Date(deal.valid_from).toLocaleDateString()}
              {deal.valid_from && deal.valid_to && " – "}
              {deal.valid_to && new Date(deal.valid_to).toLocaleDateString()}
            </p>
          )}

          {/* Add / Remove */}
          <button
            onClick={() => inList ? removeItem(deal.id) : addItem(deal)}
            className={cn(
              "w-full flex items-center justify-center gap-2 py-3 rounded-xl font-semibold text-sm transition-colors",
              inList
                ? "bg-[var(--bg-elevated)] border border-[var(--border)] text-[var(--text-secondary)] hover:border-red-500 hover:text-red-400"
                : "bg-[var(--green)] text-black hover:bg-[var(--green-dim)]"
            )}
          >
            {inList ? (
              <><Trash2 size={15} /> Remove from list</>
            ) : (
              <><ShoppingCart size={15} /> Add to grocery list</>
            )}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

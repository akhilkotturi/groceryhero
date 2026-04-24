"use client";
import { motion, AnimatePresence } from "framer-motion";
import Image from "next/image";
import { X, Trash2, ShoppingCart, Tag } from "lucide-react";
import { useGroceryStore } from "@/lib/grocery-store";

export function GroceryList() {
  const { items, isOpen, setOpen, removeItem, openModal } = useGroceryStore();

  const totalSavings = items.reduce((sum, item) => {
    const d = item.deal;
    if (d.original_price && (d.sale_price ?? d.unit_price)) {
      return sum + (d.original_price - (d.sale_price ?? d.unit_price ?? 0));
    }
    return sum;
  }, 0);

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop (mobile only) */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-30 bg-black/40 sm:hidden"
            onClick={() => setOpen(false)}
          />

          {/* Drawer */}
          <motion.div
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 32 }}
            className="fixed right-0 top-0 bottom-0 z-40 w-[340px] bg-[var(--bg-card)] border-l border-[var(--border)] flex flex-col shadow-2xl"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-4 border-b border-[var(--border)] shrink-0">
              <div className="flex items-center gap-2">
                <ShoppingCart size={16} className="text-[var(--green)]" />
                <span className="font-semibold text-[var(--text-primary)]" style={{ fontFamily: "Syne, sans-serif" }}>
                  Grocery List
                </span>
                {items.length > 0 && (
                  <span className="text-xs bg-[var(--green)] text-black font-bold px-1.5 py-0.5 rounded-full">
                    {items.length}
                  </span>
                )}
              </div>
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                <X size={18} />
              </button>
            </div>

            {/* List */}
            <div className="flex-1 overflow-y-auto">
              {items.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-center px-6">
                  <ShoppingCart size={32} className="text-[var(--text-muted)]" />
                  <p className="text-sm text-[var(--text-secondary)]">Your list is empty</p>
                  <p className="text-xs text-[var(--text-muted)]">Tap + on any deal to add it</p>
                </div>
              ) : (
                <ul className="divide-y divide-[var(--border)]">
                  {items.map((item) => {
                    const d = item.deal;
                    const price = d.sale_price ?? d.unit_price;
                    return (
                      <li key={item.id} className="flex items-center gap-3 px-4 py-3 hover:bg-[var(--bg-elevated)] transition-colors group">
                        {/* Thumbnail — click to open modal */}
                        <button
                          onClick={() => openModal(d)}
                          className="relative w-12 h-12 rounded-lg bg-[var(--bg-elevated)] overflow-hidden shrink-0 hover:ring-2 hover:ring-[var(--green)] transition-all"
                        >
                          {d.image_url ? (
                            <Image src={d.image_url} alt={d.normalized_name ?? d.raw_title} fill sizes="48px" className="object-contain p-1" />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center">
                              <Tag size={16} className="text-[var(--text-muted)]" />
                            </div>
                          )}
                        </button>

                        {/* Info — click to open modal */}
                        <button onClick={() => openModal(d)} className="flex-1 text-left min-w-0">
                          <p className="text-sm font-medium text-[var(--text-primary)] truncate leading-snug">
                            {d.normalized_name ?? d.raw_title}
                          </p>
                          <div className="flex items-center gap-2 mt-0.5">
                            {price != null && (
                              <span className="text-xs font-bold text-[var(--green)] font-mono">
                                ${price.toFixed(2)}
                              </span>
                            )}
                            {d.store && (
                              <span className="text-xs text-[var(--text-muted)] truncate">
                                {d.store.chain}
                              </span>
                            )}
                          </div>
                        </button>

                        {/* Remove */}
                        <button
                          onClick={() => removeItem(d.id)}
                          className="shrink-0 p-1.5 text-[var(--text-muted)] hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                        >
                          <Trash2 size={14} />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            {/* Footer */}
            {items.length > 0 && (
              <div className="shrink-0 px-4 py-4 border-t border-[var(--border)] space-y-3">
                {totalSavings > 0 && (
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-[var(--text-muted)]">Est. savings</span>
                    <span className="font-bold text-[var(--green)] font-mono">
                      ${totalSavings.toFixed(2)}
                    </span>
                  </div>
                )}
                <button
                  onClick={() => {
                    items.forEach((i) => removeItem(i.deal.id));
                  }}
                  className="w-full py-2 text-xs text-[var(--text-muted)] hover:text-red-400 transition-colors border border-[var(--border)] rounded-lg hover:border-red-500/40"
                >
                  Clear all
                </button>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

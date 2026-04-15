"use client";
import { create } from "zustand";
import { Deal } from "@/types";

interface PlanStore {
  /** Ordered list of deal IDs in the plan. */
  dealIds: string[];
  /** Full Deal objects, kept in sync with dealIds. */
  deals: Deal[];
  addDeal: (deal: Deal) => void;
  removeDeal: (dealId: string) => void;
  clearPlan: () => void;
  isInPlan: (dealId: string) => boolean;
}

export const usePlanStore = create<PlanStore>()((set, get) => ({
  dealIds: [],
  deals: [],

  addDeal: (deal: Deal) => {
    if (get().dealIds.includes(deal.id)) return;
    set((s) => ({
      dealIds: [...s.dealIds, deal.id],
      deals: [...s.deals, deal],
    }));
  },

  removeDeal: (dealId: string) => {
    set((s) => ({
      dealIds: s.dealIds.filter((id) => id !== dealId),
      deals: s.deals.filter((d) => d.id !== dealId),
    }));
  },

  clearPlan: () => set({ dealIds: [], deals: [] }),

  isInPlan: (dealId: string) => get().dealIds.includes(dealId),
}));

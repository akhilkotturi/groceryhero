"use client";
import { create } from "zustand";
import api from "@/lib/api";
import { Deal } from "@/types";

export interface GroceryItem {
  id: string;
  deal_id: string;
  added_at: string;
  deal: Deal;
}

interface GroceryState {
  items: GroceryItem[];
  isOpen: boolean;
  modalDeal: Deal | null;
  isLoading: boolean;

  fetchList: () => Promise<void>;
  addItem: (deal: Deal) => Promise<void>;
  removeItem: (dealId: string) => Promise<void>;
  isInList: (dealId: string) => boolean;
  setOpen: (open: boolean) => void;
  openModal: (deal: Deal) => void;
  closeModal: () => void;
}

export const useGroceryStore = create<GroceryState>()((set, get) => ({
  items: [],
  isOpen: false,
  modalDeal: null,
  isLoading: false,

  fetchList: async () => {
    set({ isLoading: true });
    try {
      const { data } = await api.get("/api/grocery-list");
      set({ items: data.items });
    } catch {
      // silent — user may not be logged in yet
    } finally {
      set({ isLoading: false });
    }
  },

  addItem: async (deal: Deal) => {
    const optimistic: GroceryItem = {
      id: `temp-${deal.id}`,
      deal_id: deal.id,
      added_at: new Date().toISOString(),
      deal,
    };
    set((s) => ({ items: [optimistic, ...s.items] }));
    try {
      const { data } = await api.post(`/api/grocery-list/${deal.id}`);
      set((s) => ({
        items: s.items.map((i) => (i.id === optimistic.id ? data : i)),
      }));
    } catch (err: any) {
      if (err?.response?.status === 409) return; // already in list, keep optimistic
      set((s) => ({ items: s.items.filter((i) => i.id !== optimistic.id) }));
    }
  },

  removeItem: async (dealId: string) => {
    const prev = get().items;
    set((s) => ({ items: s.items.filter((i) => i.deal_id !== dealId) }));
    try {
      await api.delete(`/api/grocery-list/${dealId}`);
    } catch {
      set({ items: prev });
    }
  },

  isInList: (dealId: string) => get().items.some((i) => i.deal_id === dealId),

  setOpen: (open: boolean) => set({ isOpen: open }),
  openModal: (deal: Deal) => set({ modalDeal: deal }),
  closeModal: () => set({ modalDeal: null }),
}));

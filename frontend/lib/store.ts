import { create } from "zustand";
import { persist } from "zustand/middleware";
import api from "@/lib/api";

export interface User {
  id: string;
  email: string;
  username: string;
  zip_code?: string;
  latitude?: number;
  longitude?: number;
  household_size?: number;
  weekly_budget?: number;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  setUser: (user: User | null) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  fetchMe: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isLoading: false,

      setUser: (user) => set({ user }),

      login: async (email, password) => {
        set({ isLoading: true });
        try {
          const { data } = await api.post("/api/auth/login", { email, password });
          set({ user: data.user });
        } finally {
          set({ isLoading: false });
        }
      },

      register: async (email, username, password) => {
        set({ isLoading: true });
        try {
          const { data } = await api.post("/api/auth/register", {
            email,
            username,
            password,
          });
          set({ user: data.user });
        } finally {
          set({ isLoading: false });
        }
      },

      logout: async () => {
        await api.post("/api/auth/logout").catch(() => {});
        set({ user: null });
        window.location.href = "/auth/login";
      },

      fetchMe: async () => {
        try {
          const { data } = await api.get("/api/users/me");
          set({ user: data });
        } catch {
          set({ user: null });
        }
      },
    }),
    {
      name: "groceryhero-auth",
      partialize: (state) => ({ user: state.user }),
    }
  )
);

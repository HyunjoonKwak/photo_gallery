import { create } from "zustand";
import type { UserInfo } from "../api/types";

interface AuthState {
  user: UserInfo | null;
  setUser: (user: UserInfo | null) => void;
}

// UI-side auth state (Zustand). Server state (the actual session) lives in the
// HttpOnly cookie + React Query cache; this just mirrors who is logged in.
export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
}));

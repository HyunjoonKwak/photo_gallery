/** Minimal toast store. Action-carrying toasts stay 8s and pause on hover
 * (docs/IMPROVEMENTS.md B-6); the Undo action wires in with real file ops. */

import { create } from "zustand";

export interface Toast {
  id: number;
  message: string;
}

let nextId = 1;

interface ToastState {
  toasts: Toast[];
  push: (message: string) => void;
  dismiss: (id: number) => void;
}

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  push: (message) =>
    set((s) => ({ toasts: [...s.toasts, { id: nextId++, message }] })),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

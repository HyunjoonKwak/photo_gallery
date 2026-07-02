/** Toast store. Action-carrying toasts (e.g. "n장 이동됨 · 되돌리기") stay 8s
 * and pause on hover (docs/IMPROVEMENTS.md B-6). */

import { create } from "zustand";

export interface ToastAction {
  label: string;
  run: () => void;
}

export interface Toast {
  id: number;
  message: string;
  action?: ToastAction;
}

let nextId = 1;

interface ToastState {
  toasts: Toast[];
  push: (message: string, action?: ToastAction) => void;
  dismiss: (id: number) => void;
}

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  push: (message, action) =>
    set((s) => ({ toasts: [...s.toasts, { id: nextId++, message, action }] })),
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}));

/** Bulk-operation progress state (IMPROVEMENTS B-6).
 *
 * One operation at a time: useFileOps starts an entry when a mutation with a
 * progress_key begins, patches it from polling, and clears it on settle. The
 * BulkProgress bar renders only when the operation has been running long
 * enough to be worth showing (no flash for quick ops).
 */

import { create } from "zustand";

export interface BulkProgress {
  key: string;
  label: string; // 이동 | 복사 | 삭제 | 되돌리기
  done: number;
  total: number;
  startedAt: number;
}

interface ProgressState {
  current: BulkProgress | null;
  start: (key: string, label: string) => void;
  patch: (key: string, done: number, total: number, label?: string) => void;
  clear: (key: string) => void;
}

export const useProgressStore = create<ProgressState>()((set, get) => ({
  current: null,
  start: (key, label) =>
    set({ current: { key, label, done: 0, total: 0, startedAt: Date.now() } }),
  patch: (key, done, total, label) => {
    const cur = get().current;
    if (!cur || cur.key !== key) return; // a newer operation took over
    set({
      current: { ...cur, done, total, label: label || cur.label },
    });
  },
  clear: (key) => {
    if (get().current?.key === key) set({ current: null });
  },
}));

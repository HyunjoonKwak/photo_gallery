/** Global filename-conflict prompt. Any move/copy path (drag-drop, 액션바,
 * 라이트박스, 분할 뷰) triggers the same dialog via this store when the backend
 * answers 409 with the conflict list, so no move can silently skip files. */

import { create } from "zustand";
import type { ConflictItem, ConflictStrategy } from "../api/types";

interface Pending {
  conflicts: ConflictItem[];
  copyMode: boolean;
  onChoose: (strategy: ConflictStrategy) => void;
}

interface ConflictState {
  pending: Pending | null;
  ask: (p: Pending) => void;
  clear: () => void;
}

export const useConflictStore = create<ConflictState>()((set) => ({
  pending: null,
  ask: (pending) => set({ pending }),
  clear: () => set({ pending: null }),
}));

/** Extract the conflict list from an ApiError-shaped 409 detail, else null. */
export function conflictsOf(err: unknown): ConflictItem[] | null {
  const detail = (err as { status?: number; detail?: unknown })?.detail;
  if (
    (err as { status?: number })?.status === 409 &&
    detail &&
    typeof detail === "object" &&
    (detail as { code?: unknown }).code === "filename_conflict"
  ) {
    return (detail as { conflicts: ConflictItem[] }).conflicts;
  }
  return null;
}

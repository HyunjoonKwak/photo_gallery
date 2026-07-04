/** Global name-conflict prompt. Any move/copy path (드래그·액션바·라이트박스·
 * 분할 뷰, 사진이든 폴더든) triggers the same dialog via this store when the
 * backend answers 409 with the conflict list, so no move can silently skip. */

import { create } from "zustand";

export type ConflictKind = "file" | "folder";

interface Pending {
  kind: ConflictKind;
  names: string[]; // conflicting filenames or folder names (display)
  copyMode: boolean;
  onChoose: (strategy: string) => void; // skip | rename | overwrite
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

/** Read a file/folder conflict out of an ApiError-shaped 409, else null. */
export function conflictInfoOf(
  err: unknown,
): { kind: ConflictKind; names: string[] } | null {
  const e = err as { status?: number; detail?: unknown };
  if (e?.status !== 409 || !e.detail || typeof e.detail !== "object") return null;
  const d = e.detail as { code?: string; conflicts?: unknown[] };
  if (d.code === "filename_conflict") {
    return {
      kind: "file",
      names: (d.conflicts ?? []).map((c) => (c as { filename: string }).filename),
    };
  }
  if (d.code === "folder_conflict") {
    return {
      kind: "folder",
      names: (d.conflicts ?? []).map((c) => (c as { name: string }).name),
    };
  }
  return null;
}

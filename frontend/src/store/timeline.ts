/** Timeline UI state: active space, selection, shift-range preview, lightbox.
 *
 * Selection rules (docs/IMPROVEMENTS.md B-3, Google Photos pattern):
 * - photo click = open, check click = select; once selection is non-empty,
 *   photo clicks toggle selection instead of opening.
 * - Shift extends a range from the anchor; holding Shift while hovering shows
 *   a live preview of the would-be range.
 * - Date-header check state is *derived* from the selection set (single
 *   source of truth — no separate per-day flags).
 */

import { create } from "zustand";
import type { PhotoFolder, PhotoItem, Space } from "../api/types";

const EMPTY_SET: ReadonlySet<string> = new Set<string>();

function rangeIds(orderedIds: string[], a: string, b: string): string[] {
  const ia = orderedIds.indexOf(a);
  const ib = orderedIds.indexOf(b);
  if (ia < 0 || ib < 0) return [];
  const [lo, hi] = ia < ib ? [ia, ib] : [ib, ia];
  return orderedIds.slice(lo, hi + 1);
}

export type ViewMode = "timeline" | "folders" | "dedup";

interface TimelineState {
  space: Space;
  setSpace: (space: Space) => void;
  viewMode: ViewMode;
  setViewMode: (mode: ViewMode) => void;
  /** Cross-view navigation: open the folder view at this breadcrumb path
   * (set by e.g. the timeline's folder panel; consumed by FolderView). */
  pendingFolderPath: PhotoFolder[] | null;
  openFolderView: (path: PhotoFolder[]) => void;
  consumePendingFolderPath: () => void;
  /** Admin only: the member whose photos are being organized (spec 4.5). */
  viewedOwner: string | null;
  setViewedOwner: (owner: string | null) => void;

  // --- selection ---
  selected: ReadonlySet<string>;
  anchorId: string | null;
  orderedIds: string[];
  itemsById: ReadonlyMap<string, PhotoItem>;
  previewIds: ReadonlySet<string>;
  shiftHeld: boolean;
  hoverId: string | null;

  setOrdered: (items: PhotoItem[]) => void;
  /** Check-circle / selection-mode click: shift extends range, else toggles. */
  selectClick: (id: string, shiftKey: boolean) => void;
  setMany: (ids: string[], on: boolean) => void;
  replaceSelection: (ids: string[]) => void;
  clearSelection: () => void;
  setShift: (held: boolean) => void;
  setHover: (id: string | null) => void;

  // --- lightbox ---
  lightboxId: string | null;
  openLightbox: (id: string) => void;
  closeLightbox: () => void;
  stepLightbox: (dir: 1 | -1) => void;
}

function computePreview(
  s: Pick<TimelineState, "shiftHeld" | "anchorId" | "hoverId" | "orderedIds">,
): ReadonlySet<string> {
  if (!s.shiftHeld || !s.anchorId || !s.hoverId || s.anchorId === s.hoverId) {
    return EMPTY_SET;
  }
  const ids = rangeIds(s.orderedIds, s.anchorId, s.hoverId);
  return ids.length ? new Set(ids) : EMPTY_SET;
}

export const useTimelineStore = create<TimelineState>()((set, get) => ({
  space: "team",
  setSpace: (space) =>
    set({
      space,
      selected: EMPTY_SET,
      anchorId: null,
      previewIds: EMPTY_SET,
      hoverId: null,
      orderedIds: [],
      itemsById: new Map(),
      lightboxId: null,
    }),
  viewMode: "timeline",
  setViewMode: (viewMode) =>
    set({ viewMode, selected: EMPTY_SET, anchorId: null, lightboxId: null }),
  pendingFolderPath: null,
  openFolderView: (path) =>
    set({
      viewMode: "folders",
      pendingFolderPath: path,
      selected: EMPTY_SET,
      anchorId: null,
      lightboxId: null,
    }),
  consumePendingFolderPath: () => set({ pendingFolderPath: null }),
  viewedOwner: null,
  setViewedOwner: (viewedOwner) => set({ viewedOwner }),

  selected: EMPTY_SET,
  anchorId: null,
  orderedIds: [],
  itemsById: new Map(),
  previewIds: EMPTY_SET,
  shiftHeld: false,
  hoverId: null,

  setOrdered: (items) =>
    set({
      orderedIds: items.map((i) => i.id),
      itemsById: new Map(items.map((i) => [i.id, i])),
    }),

  selectClick: (id, shiftKey) => {
    const s = get();
    if (shiftKey && s.anchorId && s.anchorId !== id) {
      const next = new Set(s.selected);
      for (const rid of rangeIds(s.orderedIds, s.anchorId, id)) next.add(rid);
      set({ selected: next, previewIds: EMPTY_SET });
      return;
    }
    const next = new Set(s.selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    set({ selected: next, anchorId: id });
  },

  setMany: (ids, on) => {
    const next = new Set(get().selected);
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    set({ selected: next, anchorId: on ? (ids[ids.length - 1] ?? null) : null });
  },

  replaceSelection: (ids) =>
    set({ selected: new Set(ids), anchorId: ids[ids.length - 1] ?? null }),

  clearSelection: () =>
    set({ selected: EMPTY_SET, anchorId: null, previewIds: EMPTY_SET }),

  setShift: (held) => {
    const s = get();
    set({ shiftHeld: held, previewIds: computePreview({ ...s, shiftHeld: held }) });
  },

  setHover: (id) => {
    const s = get();
    set({ hoverId: id, previewIds: computePreview({ ...s, hoverId: id }) });
  },

  lightboxId: null,
  openLightbox: (id) => set({ lightboxId: id }),
  closeLightbox: () => set({ lightboxId: null }),
  stepLightbox: (dir) => {
    const s = get();
    if (!s.lightboxId) return;
    const idx = s.orderedIds.indexOf(s.lightboxId);
    const next = s.orderedIds[idx + dir];
    if (next) set({ lightboxId: next });
  },
}));

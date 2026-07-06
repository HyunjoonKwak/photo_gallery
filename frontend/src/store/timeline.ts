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

/** 상위 3영역: 사진 뷰어(감상) / 앨범(사람·장소·비디오) / 폴더 분류(정리). */
export type Section = "viewer" | "albums" | "manage";
/** 사진 뷰어 줌 레벨. */
export type ViewerZoom = "year" | "month" | "day" | "folder";
/** 앨범 종류. */
export type AlbumKind = "people" | "places" | "videos";
/** 폴더 분류 서브탭. */
export type ManageTab = "folders" | "dedup" | "search";
export type FolderDisplay = "grid" | "list";

/** 화면/라이브러리 전환 시 감상·선택 상태 초기화 묶음(매번 새 컬렉션). */
function resetView() {
  return {
    selected: EMPTY_SET,
    anchorId: null,
    previewIds: EMPTY_SET,
    hoverId: null,
    orderedIds: [] as string[],
    itemsById: new Map<string, PhotoItem>(),
    lightboxId: null,
  };
}

const FOLDER_DISPLAY_KEY = "nasphoto.folderDisplay";

function initialFolderDisplay(): FolderDisplay {
  try {
    return localStorage.getItem(FOLDER_DISPLAY_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

interface TimelineState {
  space: Space;
  setSpace: (space: Space) => void;
  // --- 상위 영역 + 영역별 서브상태 ---
  section: Section;
  setSection: (s: Section) => void;
  /** 사진 뷰어 줌 + 드릴/스크롤 컨텍스트. */
  zoom: ViewerZoom;
  focusYear: string | null; // "2024"
  focusMonth: string | null; // "2024-03"
  focusDay: string | null; // "2024-03-15"
  setZoom: (z: ViewerZoom) => void;
  drillTo: (ctx: {
    zoom: ViewerZoom;
    year?: string;
    month?: string;
    day?: string;
  }) => void;
  /** 앨범: 종류 + 열린 그룹(인물/장소). */
  albumKind: AlbumKind;
  groupId: string | null;
  groupLabel: string | null;
  setAlbumKind: (k: AlbumKind) => void;
  openGroup: (id: string, label: string) => void;
  closeGroup: () => void;
  /** 폴더 분류 서브탭. */
  manageTab: ManageTab;
  setManageTab: (t: ManageTab) => void;
  /** Cross-view navigation: open the folder view at this breadcrumb path
   * (set by e.g. the timeline's folder panel; consumed by FolderView). */
  pendingFolderPath: PhotoFolder[] | null;
  openFolderView: (path: PhotoFolder[]) => void;
  consumePendingFolderPath: () => void;
  /** Folder view: show sub-folders as icon cards or a list (persisted). */
  folderDisplay: FolderDisplay;
  setFolderDisplay: (d: FolderDisplay) => void;
  /** Photo search: submitting a query switches to the search view. */
  searchQuery: string;
  runSearch: (query: string) => void;
  /** Admin only: the member whose photos are being organized (spec 4.5). */
  viewedOwner: string | null;
  setViewedOwner: (owner: string | null) => void;
  /** 1차 구역(기기 백업): 활성 시 FileStation 폴더 뷰만. owner와 배타적. */
  activeZone: { id: string; label: string } | null;
  /** Library selector: 공용 / 내 사진 / 타인 / 1차 구역을 한 축으로 전환. */
  selectLibrary: (lib: {
    space: Space;
    owner: string | null;
    zone?: { id: string; label: string } | null;
  }) => void;

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

  // --- 뒤로가기 네비게이션 ---
  // 화면 안의 드릴다운(폴더 경로·장소 지역 등 컴포넌트 로컬 상태)은 여기에
  // "한 단계 위로" 핸들러를 등록한다. goBack이 우선순위대로 한 단계 되돌린다.
  _backHandlers: (() => void)[];
  registerBack: (fn: () => void) => () => void;
  /** 한 단계 뒤로. 되돌릴 게 있으면 실행하고 true, 최상위면 false. */
  goBack: () => boolean;
  /** 뒤로 갈 곳이 있는지(브라우저 트랩·버튼 표시용). */
  canGoBack: () => boolean;
  /** 기본 화면(사진·연 뷰)으로. 앨범/폴더 드릴은 컴포넌트 언마운트로 리셋. */
  goHome: () => void;
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
  setSpace: (space) => set({ space, ...resetView() }),

  section: "viewer",
  // 타인/1차 구역은 폴더 분류에서만 표현 가능 → 다른 영역으로 갈 땐 자기
  // 라이브러리로 스냅백(공용/개인)하고 감상 상태를 초기화한다.
  setSection: (section) =>
    set((s) => ({
      section,
      ...(section !== "manage" && (s.viewedOwner || s.activeZone)
        ? { viewedOwner: null, activeZone: null }
        : {}),
      ...resetView(),
    })),

  zoom: "year",
  focusYear: null,
  focusMonth: null,
  focusDay: null,
  setZoom: (zoom) => set({ zoom, ...resetView() }),
  drillTo: (ctx) =>
    set((s) => ({
      zoom: ctx.zoom,
      focusYear: ctx.year ?? s.focusYear,
      focusMonth: ctx.month ?? s.focusMonth,
      focusDay: ctx.day ?? s.focusDay,
      ...resetView(),
    })),

  albumKind: "people",
  groupId: null,
  groupLabel: null,
  setAlbumKind: (albumKind) =>
    set({ albumKind, groupId: null, groupLabel: null, ...resetView() }),
  openGroup: (groupId, groupLabel) =>
    set({ groupId, groupLabel, ...resetView() }),
  closeGroup: () => set({ groupId: null, groupLabel: null, ...resetView() }),

  manageTab: "folders",
  setManageTab: (manageTab) => set({ manageTab, ...resetView() }),

  pendingFolderPath: null,
  openFolderView: (path) =>
    set({
      section: "manage",
      manageTab: "folders",
      pendingFolderPath: path,
      ...resetView(),
    }),
  consumePendingFolderPath: () => set({ pendingFolderPath: null }),
  searchQuery: "",
  runSearch: (query) =>
    set({
      searchQuery: query,
      section: "manage",
      manageTab: "search",
      ...resetView(),
    }),
  folderDisplay: initialFolderDisplay(),
  setFolderDisplay: (folderDisplay) => {
    try {
      localStorage.setItem(FOLDER_DISPLAY_KEY, folderDisplay);
    } catch {
      // private mode etc. — preference just won't persist
    }
    set({ folderDisplay });
  },
  viewedOwner: null,
  // Switching whose photos we organize: another member's personal space is
  // folder-view only (Photos' timeline/AI index is per-session), so jump to
  // 폴더 분류/folders and reset selection state.
  setViewedOwner: (viewedOwner) =>
    set({
      viewedOwner,
      activeZone: null,
      section: "manage",
      manageTab: "folders",
      ...resetView(),
    }),
  activeZone: null,
  selectLibrary: ({ space, owner, zone }) =>
    set({
      space,
      viewedOwner: owner,
      activeZone: zone ?? null,
      // 타인·1차 구역은 폴더 분류 전용 → 그리로 강제; 그 외엔 현재 영역 유지
      ...(owner || zone
        ? { section: "manage" as Section, manageTab: "folders" as ManageTab }
        : {}),
      ...resetView(),
    }),

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

  _backHandlers: [],
  registerBack: (fn) => {
    set((s) => ({ _backHandlers: [...s._backHandlers, fn] }));
    return () =>
      set((s) => ({ _backHandlers: s._backHandlers.filter((h) => h !== fn) }));
  },
  goBack: () => {
    const s = get();
    // 우선순위: 라이트박스 → 화면 내 드릴(폴더/장소) → 앨범 그룹 →
    // 뷰어 줌(→연) → 다른 영역(→사진).
    if (s.lightboxId) {
      set({ lightboxId: null });
      return true;
    }
    if (s._backHandlers.length) {
      s._backHandlers[s._backHandlers.length - 1]();
      return true;
    }
    if (s.groupId) {
      s.closeGroup();
      return true;
    }
    if (s.section === "viewer" && s.zoom !== "year") {
      s.setZoom("year");
      return true;
    }
    if (s.section !== "viewer") {
      s.setSection("viewer");
      return true;
    }
    return false;
  },
  canGoBack: () => {
    const s = get();
    return Boolean(
      s.lightboxId ||
        s._backHandlers.length ||
        s.groupId ||
        (s.section === "viewer" && s.zoom !== "year") ||
        s.section !== "viewer",
    );
  },
  goHome: () =>
    set({
      section: "viewer",
      zoom: "year",
      focusYear: null,
      focusMonth: null,
      focusDay: null,
      groupId: null,
      groupLabel: null,
      viewedOwner: null,
      activeZone: null,
      ...resetView(),
    }),
}));

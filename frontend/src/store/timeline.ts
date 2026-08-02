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
import { useToastStore } from "./toast";

const EMPTY_SET: ReadonlySet<string> = new Set<string>();

function rangeIds(orderedIds: string[], a: string, b: string): string[] {
  const ia = orderedIds.indexOf(a);
  const ib = orderedIds.indexOf(b);
  if (ia < 0 || ib < 0) return [];
  const [lo, hi] = ia < ib ? [ia, ib] : [ib, ia];
  return orderedIds.slice(lo, hi + 1);
}

/** 상위 3영역: 사진 뷰어(감상·모든 렌즈) / 앨범(사용자 큐레이션) / 폴더 분류(정리). */
export type Section = "viewer" | "albums" | "manage" | "more";
/** 사진 뷰어 렌즈(감상 축) — 타임라인/폴더/사람/장소/비디오. AI 자동 그룹
 * (사람·장소·비디오)은 "앨범"이 아니라 감상 렌즈라 뷰어 아래로 편입한다.
 * "앨범"은 사용자가 만드는 큐레이션 전용. */
export type ViewerLens = "timeline" | "folder" | "people" | "places" | "videos";
/** 타임라인 렌즈 내부 줌(연/월/일). */
export type ViewerZoom = "year" | "month" | "day";
/** 폴더 분류 서브탭. */
export type ManageTab = "folders" | "dedup" | "junk" | "search";
export type FolderDisplay = "grid" | "list";

/** Folder view ordering (persisted). key: 이름 | 날짜(생성일); dir: 오름/내림차순. */
export type FolderSortKey = "name" | "date";
export type FolderSortDir = "asc" | "desc";
export interface FolderSort {
  key: FolderSortKey;
  dir: FolderSortDir;
}

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
    visibleGroupLabel: null as string | null,
  };
}

/** 뒤로가기 히스토리에 담는 네비게이션 스냅샷 — 영역/탭/라이브러리 축을
 * 통째로 저장해, 복원 시 그 화면을 그대로 되살린다(줌·그룹 포함). */
interface NavSnapshot {
  section: Section;
  viewerLens: ViewerLens;
  zoom: ViewerZoom;
  focusYear: string | null;
  focusMonth: string | null;
  focusDay: string | null;
  groupId: string | null;
  groupLabel: string | null;
  manageTab: ManageTab;
  space: Space;
  viewedOwner: string | null;
  activeZone: { id: string; label: string } | null;
  searchQuery: string;
}

const NAV_HISTORY_MAX = 50;

const FOLDER_DISPLAY_KEY = "nasphoto.folderDisplay";
const FOLDER_SORT_KEY = "nasphoto.folderSort";

function initialFolderDisplay(): FolderDisplay {
  try {
    return localStorage.getItem(FOLDER_DISPLAY_KEY) === "list" ? "list" : "grid";
  } catch {
    return "grid";
  }
}

function initialFolderSort(): FolderSort {
  try {
    const raw = localStorage.getItem(FOLDER_SORT_KEY);
    if (raw) {
      const p = JSON.parse(raw) as Partial<FolderSort>;
      const key: FolderSortKey = p.key === "date" ? "date" : "name";
      const dir: FolderSortDir = p.dir === "desc" ? "desc" : "asc";
      return { key, dir };
    }
  } catch {
    // fall through to default
  }
  return { key: "name", dir: "asc" };
}

interface TimelineState {
  space: Space;
  setSpace: (space: Space) => void;
  // --- 상위 영역 + 영역별 서브상태 ---
  section: Section;
  setSection: (s: Section) => void;
  /** 사진 뷰어 렌즈(타임라인/폴더/사람/장소/비디오). */
  viewerLens: ViewerLens;
  setViewerLens: (lens: ViewerLens) => void;
  /** 타임라인 렌즈 줌 + 드릴/스크롤 컨텍스트. */
  zoom: ViewerZoom;
  focusYear: string | null; // "2024"
  focusMonth: string | null; // "2024-03"
  focusDay: string | null; // "2024-03-15"
  visibleGroupLabel: string | null;
  setVisibleGroupLabel: (label: string | null) => void;
  setZoom: (z: ViewerZoom) => void;
  drillTo: (ctx: {
    zoom: ViewerZoom;
    year?: string;
    month?: string;
    day?: string;
  }) => void;
  /** 사람 렌즈: 열린 인물 그룹. */
  groupId: string | null;
  groupLabel: string | null;
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
  /** Folder view: sub-folder ordering — 이름/날짜 × 오름/내림 (persisted). */
  folderSort: FolderSort;
  setFolderSort: (s: FolderSort) => void;
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

  // --- 우측 날짜 스크러버 표시 여부 ---
  // 스크러버(연/월 라벨 레일)가 화면에 있으면 NavControls 플로팅 버튼이
  // 레일 왼쪽으로 비켜난다(겹침 방지). 전환 중 이중 마운트 대비 카운터.
  scrubberCount: number;
  scrubberMounted: () => void;
  scrubberUnmounted: () => void;

  // --- 처음 안내 다시 보기 (더보기 → FirstRunTip 재표시) ---
  // 실수로 닫으면(배경 탭 포함) 계정당 1회라 다시 볼 수 없던 문제의 해소.
  // 틱 증가 = 1회 재표시 요청(영구 재활성화 아님 — localStorage는 유지).
  firstRunTipTick: number;
  showFirstRunTip: () => void;

  // --- 뒤로가기 네비게이션 ---
  // 영역/탭/라이브러리 전환은 여기에 직전 화면 스냅샷을 쌓아, 뒤로가기가
  // 방문 순서를 그대로 역추적한다(사진→앨범→폴더분류 뒤로 시 앨범 경유).
  _navHistory: NavSnapshot[];
  // 화면 안의 드릴다운(폴더 경로·장소 지역 등 컴포넌트 로컬 상태)은 여기에
  // "한 단계 위로" 핸들러를 등록한다. goBack이 우선순위대로 한 단계 되돌린다.
  _backHandlers: (() => void)[];
  registerBack: (fn: () => void) => () => void;
  // 화면-로컬 드릴다운의 "되돌릴 단계 수"(폴더 경로 깊이·지역 열림 등). 마운트된
  // 드릴 컴포넌트가 보고한다(동시에 하나만 마운트). 뒤로가기 히스토리 미러링이
  // 이 수만큼 실제 history 항목을 쌓아, 안드로이드 Chrome이 센티넬을 건너뛰지
  // 않게 한다(전진 탭 시점에 push → 사용자 활성 유효 → non-skippable).
  screenBackDepth: number;
  setScreenBackDepth: (n: number) => void;
  /** 한 단계 뒤로. 되돌릴 게 있으면 실행하고 true, 최상위면 false. */
  goBack: () => boolean;
  /** 뒤로 갈 곳이 있는지(브라우저 트랩·버튼 표시용). */
  canGoBack: () => boolean;
  /** 기본 화면(사진·연 뷰)으로. 앨범/폴더 드릴은 컴포넌트 언마운트로 리셋. */
  goHome: () => void;
}

/** 현재 네비게이션 축을 스냅샷으로 뽑는다(뒤로가기 히스토리 push용).
 *
 * 화면-로컬 드릴(타임라인 줌·사람 그룹)은 **평탄화**해서 담는다(zoom=year,
 * group=null). 이유: navHistory 항목은 "뒤로가기 1회 = 1항목"이라는 불변을
 * 지켜야 selectBackDepth가 정확한데, 드릴 상태를 그대로 담으면 복원 시 그 항목이
 * 여러 단계(줌→연, 그룹 닫기)를 숨겨 깊이 계산이 어긋나고, 되돌아올 때 popstate
 * 도중 센티넬을 push하게 된다(안드로이드 skippable 재발). 폴더 경로가 영역 전환
 * 때 초기화되는 것과 동일한 절충 — 렌즈/영역을 넘나든 뒤 돌아오면 그 화면의
 * 최상단(연 뷰·인물 목록)으로 온다. */
function navSnapshot(s: TimelineState): NavSnapshot {
  return {
    section: s.section,
    viewerLens: s.viewerLens,
    zoom: "year",
    focusYear: null,
    focusMonth: null,
    focusDay: null,
    groupId: null,
    groupLabel: null,
    manageTab: s.manageTab,
    space: s.space,
    viewedOwner: s.viewedOwner,
    activeZone: s.activeZone,
    searchQuery: s.searchQuery,
  };
}

/** 영역/탭/라이브러리 전환 patch를 만들되, 직전 화면을 히스토리에 쌓는다.
 * goBack이 이 스택을 역순으로 pop 해 "순차적" 뒤로가기를 보장한다. */
function withNav(
  s: TimelineState,
  patch: Partial<TimelineState>,
): Partial<TimelineState> {
  return {
    _navHistory: [...s._navHistory, navSnapshot(s)].slice(-NAV_HISTORY_MAX),
    ...patch,
  };
}

/** 현재 화면에서 최상위(더 되돌릴 것 없음)까지 뒤로가기로 소비되는 "단계 수".
 * goBack의 우선순위 분기(라이트박스→화면로컬→그룹→줌→영역히스토리)가 각각
 * 한 단계씩 소비하므로, 그 합이 곧 이 값이다. useBackTrap이 이 수만큼 실제
 * 브라우저 히스토리 항목을 유지해, 뒤로가기가 1:1로 정확히 매핑되게 한다. */
export function selectBackDepth(s: TimelineState): number {
  return (
    (s.lightboxId ? 1 : 0) +
    s.screenBackDepth +
    (s.groupId ? 1 : 0) +
    (s.section === "viewer" &&
    s.viewerLens === "timeline" &&
    s.zoom !== "year"
      ? 1
      : 0) +
    s._navHistory.length
  );
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
    set((s) => (s.space === space ? {} : withNav(s, { space, ...resetView() }))),

  section: "viewer",
  // 타인/기기 백업은 정리에서만 표현 가능 → 감상 영역으로 갈 땐 자기
  // 라이브러리로 스냅백(가족/개인)하고 감상 상태를 초기화한다.
  // 더보기는 사진 화면이 아니라 스냅백 없이 통과(휴지통 확인 후 복귀 가능).
  setSection: (section) => {
    const s = get();
    if (section === s.section) return;
    const snapback =
      section !== "manage" &&
      section !== "more" &&
      (s.viewedOwner != null || s.activeZone != null);
    // 조용히 풀리면 "보던 게 사라졌다"가 되므로 복귀를 알린다(IA 3단계).
    if (snapback) {
      useToastStore
        .getState()
        .push(
          s.activeZone
            ? "기기 백업에서 나와 내 사진으로 돌아왔어요."
            : "구성원 사진에서 나와 내 사진으로 돌아왔어요.",
        );
    }
    set(
      withNav(s, {
        section,
        // 영역 전환은 항상 그 영역의 기본 화면으로(뷰어=타임라인·연 뷰).
        viewerLens: "timeline",
        zoom: "year",
        groupId: null,
        groupLabel: null,
        ...(snapback ? { viewedOwner: null, activeZone: null } : {}),
        ...resetView(),
      }),
    );
  },

  viewerLens: "timeline",
  // 렌즈 전환은 뒤로가기 히스토리에 쌓아(이전 렌즈로 복귀), 줌·그룹은 초기화.
  setViewerLens: (viewerLens) =>
    set((s) =>
      s.viewerLens === viewerLens
        ? {}
        : withNav(s, {
            viewerLens,
            zoom: "year",
            groupId: null,
            groupLabel: null,
            ...resetView(),
          }),
    ),

  zoom: "year",
  focusYear: null,
  focusMonth: null,
  focusDay: null,
  // 뷰포트 최상단에 실제로 보이는 그룹 라벨(월뷰 크럼이 스크롤을 따라가게).
  visibleGroupLabel: null,
  setVisibleGroupLabel: (visibleGroupLabel: string | null) => {
    if (get().visibleGroupLabel !== visibleGroupLabel) set({ visibleGroupLabel });
  },
  setZoom: (zoom) => set({ zoom, ...resetView() }),
  drillTo: (ctx) =>
    set((s) => ({
      zoom: ctx.zoom,
      focusYear: ctx.year ?? s.focusYear,
      focusMonth: ctx.month ?? s.focusMonth,
      focusDay: ctx.day ?? s.focusDay,
      ...resetView(),
    })),

  groupId: null,
  groupLabel: null,
  openGroup: (groupId, groupLabel) =>
    set({ groupId, groupLabel, ...resetView() }),
  closeGroup: () => set({ groupId: null, groupLabel: null, ...resetView() }),

  manageTab: "folders",
  setManageTab: (manageTab) =>
    set((s) =>
      s.manageTab === manageTab ? {} : withNav(s, { manageTab, ...resetView() }),
    ),

  pendingFolderPath: null,
  openFolderView: (path) =>
    set((s) =>
      withNav(s, {
        section: "manage",
        manageTab: "folders",
        pendingFolderPath: path,
        ...resetView(),
      }),
    ),
  consumePendingFolderPath: () => set({ pendingFolderPath: null }),
  searchQuery: "",
  runSearch: (query) =>
    set((s) =>
      withNav(s, {
        searchQuery: query,
        section: "manage",
        manageTab: "search",
        ...resetView(),
      }),
    ),
  folderDisplay: initialFolderDisplay(),
  setFolderDisplay: (folderDisplay) => {
    try {
      localStorage.setItem(FOLDER_DISPLAY_KEY, folderDisplay);
    } catch {
      // private mode etc. — preference just won't persist
    }
    set({ folderDisplay });
  },
  folderSort: initialFolderSort(),
  setFolderSort: (folderSort) => {
    try {
      localStorage.setItem(FOLDER_SORT_KEY, JSON.stringify(folderSort));
    } catch {
      // private mode etc. — preference just won't persist
    }
    set({ folderSort });
  },
  viewedOwner: null,
  // Switching whose photos we organize: another member's personal space is
  // folder-view only (Photos' timeline/AI index is per-session), so jump to
  // 폴더 분류/folders and reset selection state.
  setViewedOwner: (viewedOwner) =>
    set((s) =>
      withNav(s, {
        viewedOwner,
        activeZone: null,
        section: "manage",
        manageTab: "folders",
        ...resetView(),
      }),
    ),
  activeZone: null,
  selectLibrary: ({ space, owner, zone }) =>
    set((s) =>
      withNav(s, {
        space,
        viewedOwner: owner,
        activeZone: zone ?? null,
        // 타인·기기 백업은 정리 전용 → 그리로 강제. 더보기(허브)는 라이브러리
        // 콘텐츠를 렌더하지 않으므로 일반 라이브러리 선택 시 사진으로 이동
        // (no-op 데드엔드 방지). 그 외엔 현재 영역 유지.
        ...(owner || zone
          ? { section: "manage" as Section, manageTab: "folders" as ManageTab }
          : s.section === "more"
            ? { section: "viewer" as Section }
            : {}),
        ...resetView(),
      }),
    ),

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

  scrubberCount: 0,
  scrubberMounted: () =>
    set((s) => ({ scrubberCount: s.scrubberCount + 1 })),
  scrubberUnmounted: () =>
    set((s) => ({ scrubberCount: Math.max(0, s.scrubberCount - 1) })),

  firstRunTipTick: 0,
  showFirstRunTip: () =>
    set((s) => ({ firstRunTipTick: s.firstRunTipTick + 1 })),

  _navHistory: [],
  _backHandlers: [],
  registerBack: (fn) => {
    set((s) => ({ _backHandlers: [...s._backHandlers, fn] }));
    return () =>
      set((s) => ({ _backHandlers: s._backHandlers.filter((h) => h !== fn) }));
  },
  screenBackDepth: 0,
  setScreenBackDepth: (n) =>
    set((s) => (s.screenBackDepth === n ? {} : { screenBackDepth: n })),
  goBack: () => {
    const s = get();
    // 우선순위(깊은 것부터): 라이트박스 → 화면 내 드릴(폴더/장소) → 사람 그룹
    // → 타임라인 줌(→연) → 영역/렌즈/라이브러리 히스토리(방문 순서 역추적).
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
    if (s.section === "viewer" && s.viewerLens === "timeline" && s.zoom !== "year") {
      s.setZoom("year");
      return true;
    }
    if (s._navHistory.length) {
      const prev = s._navHistory[s._navHistory.length - 1];
      set({
        _navHistory: s._navHistory.slice(0, -1),
        ...prev,
        ...resetView(),
      });
      return true;
    }
    return false;
  },
  canGoBack: () => {
    const s = get();
    return selectBackDepth(s) > 0;
  },
  goHome: () =>
    set({
      section: "viewer",
      viewerLens: "timeline",
      zoom: "year",
      focusYear: null,
      focusMonth: null,
      focusDay: null,
      groupId: null,
      groupLabel: null,
      viewedOwner: null,
      activeZone: null,
      _navHistory: [],
      ...resetView(),
    }),
}));

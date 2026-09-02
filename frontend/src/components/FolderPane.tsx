import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { askConfirm, askPrompt } from "./Dialog";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api, type AreaScope } from "../api/client";
import type { PhotoFolder } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useFileOps } from "../hooks/useFileOps";
import { useTimelineStore } from "../store/timeline";
import type { FolderSort, FolderSortKey } from "../store/timeline";
import { PhotoCell } from "./timeline/PhotoCell";
import { VirtualRows } from "./VirtualRows";
import { useMarqueeSelect } from "../hooks/useMarqueeSelect";
import { SPRING_MS, folderBasename } from "./FolderTree";
import { FolderNameAuditDialog } from "./FolderNameAuditDialog";
import { CaptureDateDialog, type CaptureTarget } from "./CaptureDateDialog";
import { useToastStore } from "../store/toast";
import { QueryErrorState } from "./QueryErrorState";

/** Order sub-folders by the user's chosen key/direction. Name uses a Korean,
 * numeric-aware compare (so 2·10 sort naturally); date uses mtime with folders
 * lacking a timestamp (Foto) kept at the end, name as the tiebreaker. */
function sortFolders(list: PhotoFolder[], sort: FolderSort): PhotoFolder[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  const byName = (a: PhotoFolder, b: PhotoFolder) =>
    folderBasename(a.name).localeCompare(folderBasename(b.name), "ko", {
      numeric: true,
      sensitivity: "base",
    });
  return [...list].sort((a, b) => {
    if (sort.key === "date") {
      if (a.mtime == null && b.mtime == null) return byName(a, b) * dir;
      if (a.mtime == null) return 1; // 날짜 없는 폴더는 방향과 무관하게 끝으로
      if (b.mtime == null) return -1;
      if (a.mtime !== b.mtime) return (a.mtime - b.mtime) * dir;
      return byName(a, b) * dir;
    }
    return byName(a, b) * dir;
  });
}

/** Spring-loaded drill-in: dragging over a folder card/row for a moment opens
 * it, so photos can be dropped into nested folders in one gesture (B-4). */
function useSpringOpen(isOver: boolean, open: () => void) {
  useEffect(() => {
    if (!isOver) return;
    const t = window.setTimeout(open, SPRING_MS);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOver]);
}

/** A sub-folder card in the pane — click to drill in, also a drop target.
 * `dndPrefix` keeps droppable ids unique when two panes show the same folder;
 * the real folder id rides along as droppable data (TimelineScreen reads it).
 */
function FolderCard({
  folder,
  count,
  dndPrefix,
  onOpen,
  dndEnabled,
  checked = false,
  onToggleCheck,
}: {
  folder: PhotoFolder;
  count: number | undefined;
  dndPrefix: string;
  onOpen: (f: PhotoFolder) => void;
  dndEnabled: boolean;
  checked?: boolean;
  onToggleCheck?: (f: PhotoFolder) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `${dndPrefix}folder:${folder.id}`,
    data: { folderId: folder.id },
    disabled: !dndEnabled,
  });
  useSpringOpen(isOver, () => onOpen(folder));
  return (
    <button
      ref={setNodeRef}
      onClick={() => onOpen(folder)}
      title={folder.name}
      className={`relative flex w-32 flex-col items-center gap-1 rounded-xl p-3 text-center transition-colors ${
        isOver
          ? "bg-blue-100 ring-2 ring-blue-400"
          : checked
            ? "bg-blue-50 ring-1 ring-blue-400"
            : "hover:bg-slate-100"
      }`}
    >
      {onToggleCheck && (
        <span
          role="checkbox"
          aria-checked={checked}
          onClick={(e) => {
            e.stopPropagation();
            onToggleCheck(folder);
          }}
          className={`absolute left-1.5 top-1.5 flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold ${
            checked
              ? "bg-blue-600 text-white"
              : "bg-slate-200 text-slate-400 hover:bg-slate-300"
          }`}
        >
          ✓
        </span>
      )}
      <span className="text-4xl leading-none">📁</span>
      <span className="w-full truncate text-xs text-slate-700">
        {folderBasename(folder.name)}
      </span>
      <span className="text-[10px] text-slate-400">
        {count != null ? `${count.toLocaleString()}장` : " "}
      </span>
    </button>
  );
}

/** List-view row: same behaviors as the card (drill-in click, drop target). */
function FolderRow({
  folder,
  count,
  dndPrefix,
  onOpen,
  dndEnabled,
  checked = false,
  onToggleCheck,
}: {
  folder: PhotoFolder;
  count: number | undefined;
  dndPrefix: string;
  onOpen: (f: PhotoFolder) => void;
  dndEnabled: boolean;
  checked?: boolean;
  onToggleCheck?: (f: PhotoFolder) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `${dndPrefix}folder:${folder.id}`,
    data: { folderId: folder.id },
    disabled: !dndEnabled,
  });
  useSpringOpen(isOver, () => onOpen(folder));
  return (
    <button
      ref={setNodeRef}
      onClick={() => onOpen(folder)}
      title={folder.name}
      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
        isOver
          ? "bg-blue-100 ring-2 ring-blue-400"
          : checked
            ? "bg-blue-50 ring-1 ring-blue-400"
            : "hover:bg-slate-100"
      }`}
    >
      {onToggleCheck && (
        <span
          role="checkbox"
          aria-checked={checked}
          onClick={(e) => {
            e.stopPropagation();
            onToggleCheck(folder);
          }}
          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
            checked
              ? "bg-blue-600 text-white"
              : "bg-slate-200 text-slate-400 hover:bg-slate-300"
          }`}
        >
          ✓
        </span>
      )}
      <span aria-hidden>📁</span>
      <span className="min-w-0 flex-1 truncate text-slate-700">
        {folderBasename(folder.name)}
      </span>
      {count != null && (
        <span className="shrink-0 text-xs text-slate-400">
          {count.toLocaleString()}장
        </span>
      )}
      <span className="shrink-0 text-slate-300">›</span>
    </button>
  );
}

export interface FolderPaneProps {
  /** Breadcrumb path; empty = root (both spaces' top-level folders). */
  path: PhotoFolder[];
  onPathChange: (path: PhotoFolder[]) => void;
  /** The active pane owns the global selection/ordered-items state. */
  active: boolean;
  onActivate: () => void;
  /** Unique per pane — keeps dnd droppable ids distinct across panes. */
  dndPrefix: string;
  /** Accept photo drops on the pane background into the current folder
   * (enabled on the inactive pane only — drags start from the active one). */
  dropTarget?: boolean;
  /** 폴더째 이동/복사(분할 뷰): 체크된 폴더 id 집합 + 토글 콜백.
   * 미전달 시(단일 뷰) 체크박스 자체를 렌더하지 않는다. */
  checkedFolderIds?: Set<string>;
  onToggleFolderCheck?: (f: PhotoFolder) => void;
  /** 현재 페인의 하위 폴더 전체 선택/해제 (분할 뷰 모두 선택 버튼). */
  onToggleAllFolders?: (folders: PhotoFolder[], on: boolean) => void;
  /** 페인별 영역(분할 뷰 영역 간 이동). 미전달 시 전역 스코프 사용. 조회·
   * 생성·삭제가 이 영역 스코프로 나가고, 쿼리 키에도 반영돼 페인 간 캐시가
   * 섞이지 않는다. */
  area?: AreaScope;
}

/** One Finder-style folder pane: breadcrumb + sub-folder cards (drill-in) +
 * the current folder's own photos. Used alone in the single folder view and
 * twice side-by-side in the dual-pane organize mode (IMPROVEMENTS B-4).
 */
export function FolderPane({
  path,
  onPathChange,
  active,
  onActivate,
  dndPrefix,
  dropTarget = false,
  checkedFolderIds,
  onToggleFolderCheck,
  onToggleAllFolders,
  area,
}: FolderPaneProps) {
  // 페인별 캐시 분리용 키(영역별 폴더 목록이 섞이지 않게).
  const areaKey = area
    ? `${area.space}:${area.zone ?? ""}:${area.targetUser ?? ""}`
    : "global";
  const current = path.length ? path[path.length - 1] : null;
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const ops = useFileOps();

  // 이름 정리는 경로형 id(1차 구역/타인 homes)에서만 의미 — 그 컨텍스트에서만 노출.
  const isFsScope = useTimelineStore((s) => Boolean(s.activeZone || s.viewedOwner));
  const isFsContext = isFsScope || Boolean(area?.zone || area?.targetUser);
  const [auditOpen, setAuditOpen] = useState(false);

  // 촬영일 교정 대상 판별:
  //  - 경로형 폴더(1차 구역/homes = FileStation): 파일에 EXIF/mtime 직접 기록.
  //  - Foto 폴더(내 사진/공용): Synology 인덱스의 촬영시간을 API로 변경(파일
  //    변경은 Synology가 재색인 안 해 반영 안 되므로).
  const [captureOpen, setCaptureOpen] = useState(false);
  const captureTarget = useMemo((): CaptureTarget | null => {
    if (!current) return null;
    // 경로형(1차 구역/homes)=파일 기록, Foto(내 사진/공용)=Synology 시간 변경.
    // 하위 폴더 EXIF 경로는 서버가 폴더 전체경로로 계산하므로 여기선 폴더 id만.
    if (current.id.startsWith("/homes/")) return { kind: "fs", root: current.id };
    return { kind: "foto", folder: current.id, space: current.space };
  }, [current]);
  const canCapture =
    captureTarget?.kind === "foto"
      ? ops.canLegacyDateRepair
      : ops.canMutate;

  const openFolder = (f: PhotoFolder) => onPathChange([...path, f]);
  const jumpTo = (index: number) => onPathChange(path.slice(0, index + 1));

  // 폴더 생성: 현재 위치의 하위로 (루트면 선택 라이브러리의 최상위).
  const qc = useQueryClient();

  // 현재 폴더 이름 변경(제자리). 1차 구역/homes는 FileStation.Rename(경로 id가
  // 바뀜), 내 사진/공용은 SYNO.Foto.Browse.Folder rename(id 유지). 사진·썸네일은
  // 그대로. 응답 id/name으로 현재 경로 항목을 갱신한다.
  const onRenameFolder = async () => {
    if (!ops.canMutate) return;
    if (!current) return;
    const cur = folderBasename(current.name);
    const name = await askPrompt({ title: "폴더 이름 변경", body: `'${cur}' 폴더의 새 이름`, initial: cur, confirmLabel: "변경" });
    if (!name?.trim() || name.trim() === cur) return;
    try {
      const res = await api.renameFolder(
        current.id,
        name.trim(),
        current.space,
        area,
      );
      onPathChange([
        ...path.slice(0, -1),
        { ...current, id: res.id, name: res.name },
      ]);
      qc.invalidateQueries({ queryKey: ["folders"] });
      qc.invalidateQueries({ queryKey: ["folder-counts"] });
      qc.invalidateQueries({ queryKey: ["folder-items"] });
      useToastStore
        .getState()
        .push(`이름을 '${folderBasename(res.name)}'(으)로 변경했습니다`);
    } catch (e) {
      useToastStore.getState().push((e as Error).message);
    }
  };

  const onCreateFolder = async () => {
    const name = await askPrompt({
      title: "새 폴더",
      body: current
        ? `'${folderBasename(current.name)}' 아래에 만듭니다.`
        : "최상위에 만듭니다.",
      placeholder: "폴더 이름",
      confirmLabel: "만들기",
    });
    if (!name?.trim()) return;
    const store = useTimelineStore.getState();
    const space =
      current?.space ??
      (area
        ? librarySpace
        : store.viewedOwner
          ? "personal"
          : store.space);
    ops.createFolder(space, name.trim(), current?.id, area);
  };

  // 폴더 삭제: 비어 있으면 바로 삭제, 사진·하위 폴더가 있으면 확인 후 통째로
  // 휴지통 이동(가역 — 되돌리기 가능). 빈 폴더 판단은 현재 화면에 이미 로드된
  // 직속 사진 수 + 하위 폴더 수로 한다(추가 조회 불필요).
  const onRemoveFolder = async () => {
    if (!current) return;
    const name = folderBasename(current.name);
    const hasContent = items.length > 0 || subFolders.length > 0;
    if (!hasContent) {
      if (!(await askConfirm({ title: "폴더 삭제", body: `빈 폴더 '${name}'을(를) 삭제할까요?`, confirmLabel: "삭제", danger: true }))) return;
      ops.removeFolder(
        current.space,
        current.id,
        false,
        () => onPathChange(path.slice(0, -1)),
        area,
      );
      return;
    }
    const parts = [
      items.length > 0 ? `사진 ${items.length}장` : null,
      subFolders.length > 0 ? `하위 폴더 ${subFolders.length}개` : null,
    ].filter(Boolean);
    if (
      !(await askConfirm({
        title: "폴더 삭제",
        body:
          `'${name}' 폴더에 ${parts.join("과(와) ")}이(가) 있습니다.\n` +
          `폴더와 안의 내용을 모두 휴지통으로 옮길까요?\n(되돌리기로 복원할 수 있습니다.)`,
        confirmLabel: "휴지통으로",
        danger: true,
      }))
    )
      return;
    ops.removeFolder(
      current.space,
      current.id,
      true,
      () => onPathChange(path.slice(0, -1)),
      area,
    );
  };

  // Sub-folders of the current location. At ROOT, only the selected
  // library's top folders show (라이브러리 셀렉터 스코프) — mixing both
  // spaces there was confusing; the other library stays reachable via the
  // collapsed tree section on the left.
  const globalLibrarySpace = useTimelineStore((s) =>
    s.viewedOwner || s.activeZone ? "personal" : s.space,
  );
  // 페인별 영역이 있으면 그 영역의 space로 최상위를 필터(zone/타인은 personal).
  const librarySpace = area
    ? area.zone || area.targetUser
      ? "personal"
      : area.space
    : globalLibrarySpace;
  const subQuery = useQuery({
    queryKey: ["folders", areaKey, current?.id ?? null],
    queryFn: () => api.folders(current?.id, area),
  });
  const folderSort = useTimelineStore((s) => s.folderSort);
  const setFolderSort = useTimelineStore((s) => s.setFolderSort);

  // Filtered but UNSORTED list — drives the counts query key so that changing
  // the display sort never invalidates/refetches folder-counts.
  const baseFolders = useMemo(
    () =>
      (subQuery.data?.folders ?? []).filter(
        (f) => current != null || f.space === librarySpace,
      ),
    [subQuery.data, current, librarySpace],
  );
  const subFolders = useMemo(
    () => sortFolders(baseFolders, folderSort),
    [baseFolders, folderSort],
  );

  // Subtree photo counts for the visible sub-folders (badge, 하위 폴더 포함
  // 재귀 합산). One batched request per level; failures just hide the badge.
  const countIds = useMemo(() => baseFolders.map((f) => f.id), [baseFolders]);
  // 청크(20개)별 쿼리 — 예전엔 전체 id join이 키라 폴더 1개만 바뀌어도 전부
  // 재요청됐다. 정렬 후 청크 단위 키로 나누면 변화 지점 이후 청크만 다시 온다.
  const countChunks = useMemo(() => {
    const sorted = [...countIds].sort();
    const out: string[][] = [];
    for (let i = 0; i < sorted.length; i += 20) out.push(sorted.slice(i, i + 20));
    return out;
  }, [countIds]);
  const countQueries = useQueries({
    queries: countChunks.map((chunk) => ({
      queryKey: ["folder-counts", areaKey, chunk.join(",")],
      queryFn: () => api.folderCounts(chunk, area),
      // 폴더 내용은 앱 내 작업(무효화 동반)으로만 바뀜 → 길게 신선 취급해
      // 드나들 때마다의 재요청(DSM 왕복 폭주)을 줄인다.
      staleTime: 300_000,
    })),
  });
  const counts = useMemo(() => {
    const merged: Record<string, number> = {};
    for (const q of countQueries)
      if (q.data) Object.assign(merged, q.data.counts);
    return merged;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [countQueries.map((q) => q.dataUpdatedAt).join(",")]);

  const folderDisplay = useTimelineStore((s) => s.folderDisplay);
  const setFolderDisplay = useTimelineStore((s) => s.setFolderDisplay);

  // Photos directly in the current folder (none at root). Tag each item with
  // the pane's space so thumbnails/ops use the right namespace even when the
  // global scope differs (e.g. personal folder while scope is team).
  const itemsQuery = useQuery({
    queryKey: ["folder-items", areaKey, current?.id],
    queryFn: () => api.folderItems(current!.id, undefined, area),
    enabled: current != null,
    staleTime: 300_000, // 작업 시 무효화가 신선도 보장 — 재방문 재요청 억제
  });
  const items = useMemo(
    () =>
      (itemsQuery.data?.items ?? []).map((it) => ({
        ...it,
        space: current?.space,
      })),
    [itemsQuery.data, current?.space],
  );

  // Only the active pane feeds the global selection model (single source of
  // truth for ordered ids / lightbox stepping / shift ranges).
  useEffect(() => {
    if (active) setOrdered(items);
  }, [active, items, setOrdered]);

  // 모두 선택 토글 상태 — 선택 집합에서 매 렌더 파생(2차 장부 없음)
  // (IMPROVEMENTS B-3: 이중 장부 금지).
  const photoSelState = useTimelineStore((s) => {
    if (items.length === 0) return "none" as const;
    let n = 0;
    for (const it of items) if (s.selected.has(it.id)) n++;
    if (n === 0) return "none" as const;
    return n === items.length ? ("all" as const) : ("some" as const);
  });

  // 하위 폴더 모두 선택 토글 상태 (분할 뷰) — checkedFolderIds에서 파생.
  const folderSelState = useMemo(() => {
    if (subFolders.length === 0) return "none" as const;
    const n = subFolders.filter((f) => checkedFolderIds?.has(f.id)).length;
    if (n === 0) return "none" as const;
    return n === subFolders.length ? ("all" as const) : ("some" as const);
  }, [subFolders, checkedFolderIds]);

  // Background drop target → move into this pane's current folder.
  const bgDrop = useDroppable({
    id: `${dndPrefix}bg`,
    data: current ? { folderId: current.id } : undefined,
    disabled: !ops.canMutate || !dropTarget || !current,
  });

  const gridRef = useRef<HTMLDivElement | null>(null);
  const paneScrollRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    // 초기 폭은 동기 측정 — RO 초기 전달이 지연/누락되는 환경(백그라운드 탭 등)
    // 에서 width=0에 갇혀 그리드가 영영 안 그려지는 문제 방지(2026-07-10 실측).
    setWidth(Math.floor(el.clientWidth));
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rows = useMemo(
    () => (width > 0 && items.length > 0 ? layoutBucket("folder", items, width) : []),
    [items, width],
  );
  const photoRows = useMemo(
    () => rows.filter((r) => r.kind === "photos"),
    [rows],
  );
  // 마우스 러버밴드 선택(빈 공간 드래그) — 셀 좌표는 레이아웃 데이터 기반이라
  // 가상화로 화면 밖인 사진까지 선택된다. Shift=기존 선택에 추가.
  const marqueeGridRef = useRef<HTMLDivElement | null>(null);
  const marquee = useMarqueeSelect({
    scrollRef: paneScrollRef,
    gridRef: marqueeGridRef,
    photoRows: photoRows as never,
    enabled: true,
  });
  const heightOfRow = useCallback(
    (i: number) => photoRows[i]?.height ?? 0,
    [photoRows],
  );

  return (
    <div
      ref={(el) => {
        bgDrop.setNodeRef(el);
        paneScrollRef.current = el;
      }}
      onMouseDownCapture={() => {
        if (!active) onActivate();
      }}
      className={`relative flex h-full min-w-0 flex-1 flex-col overflow-y-auto transition-colors ${
        bgDrop.isOver ? "bg-blue-50" : ""
      }`}
    >
      {/* Breadcrumb */}
      <div
        data-no-boxselect
        className={`sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b bg-white/90 px-4 py-2 text-sm backdrop-blur ${
          active ? "border-blue-200" : "border-slate-100"
        }`}
      >
        <button
          onClick={() => onPathChange([])}
          className={`rounded px-1.5 py-0.5 ${
            current ? "text-blue-600 hover:bg-slate-100" : "font-semibold text-slate-700"
          }`}
        >
          🏠 폴더
        </button>
        {path.map((f, i) => (
          <span key={f.id} className="flex items-center gap-1">
            <span className="text-slate-300">/</span>
            <button
              onClick={() => jumpTo(i)}
              className={`rounded px-1.5 py-0.5 ${
                i === path.length - 1
                  ? "font-semibold text-slate-800"
                  : "text-blue-600 hover:bg-slate-100"
              }`}
            >
              {folderBasename(f.name)}
            </button>
          </span>
        ))}
        {/* 폴더 관리: 생성(현재 위치 하위) / 삭제(빈 폴더만) / 이름 정리(1차 구역) */}
        <span className="ml-auto flex shrink-0 items-center gap-1">
          {ops.canMutate && isFsContext && (
            <button
              onClick={() => setAuditOpen(true)}
              title="이 폴더 아래에서 날짜부가 밑줄(2016_06_06)인 폴더를 하이픈으로 정리"
              className="rounded-lg border border-slate-300 px-2 py-0.5 text-xs text-slate-500 hover:border-slate-400 hover:text-slate-700"
            >
              이름 정리
            </button>
          )}
          {captureTarget && canCapture && (
            <button
              onClick={() => setCaptureOpen(true)}
              title="이 폴더 사진의 촬영일을 파일명에서 읽어 교정(복사시각으로 잘못 잡힌 날짜 정정)"
              className="rounded-lg border border-slate-300 px-2 py-0.5 text-xs text-slate-500 hover:border-slate-400 hover:text-slate-700"
            >
              촬영일 교정
            </button>
          )}
          {ops.canMutate && (
            <button
              onClick={onCreateFolder}
              disabled={ops.isBusy}
              title={current ? "이 폴더 아래 새 폴더" : "최상위에 새 폴더"}
              className="rounded-lg border border-dashed border-slate-300 px-2 py-0.5 text-xs text-slate-500 hover:border-slate-400 hover:text-slate-700 disabled:opacity-40"
            >
              ＋ 새 폴더
            </button>
          )}
          {ops.canMutate && current && (
            <button
              onClick={onRenameFolder}
              title="이 폴더의 이름 변경(사진·썸네일은 그대로)"
              className="rounded-lg border border-slate-300 px-2 py-0.5 text-xs text-slate-500 hover:border-slate-400 hover:text-slate-700"
            >
              이름 변경
            </button>
          )}
          {ops.canMutate && current && (
            <button
              onClick={onRemoveFolder}
              disabled={ops.isBusy}
              title="빈 폴더는 바로, 내용이 있으면 확인 후 통째로 휴지통으로"
              className="rounded-lg border border-red-200 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50 disabled:opacity-40"
            >
              폴더 삭제
            </button>
          )}
        </span>
      </div>

      {/* width ref on the unpadded inner box — measuring the padded box makes
       * justified rows too wide (photos overflow the right padding). */}
      <div className="flex-1 px-4 pb-10">
        <div ref={gridRef}>
        {/* Sub-folders */}
        {subQuery.isPending && (
          <p className="py-6 text-center text-sm text-slate-400">폴더 불러오는 중…</p>
        )}
        {subQuery.isError && subFolders.length === 0 && (
          <QueryErrorState
            compact
            message="폴더 목록을 불러오지 못했습니다."
            onRetry={() => void subQuery.refetch()}
          />
        )}
        {subFolders.length > 0 && (
          <section className="py-3">
            <div className="mb-1 flex items-center justify-between gap-2">
              <h3 className="shrink-0 text-xs font-semibold uppercase tracking-wide text-slate-400">
                {current ? "하위 폴더" : "폴더"} ({subFolders.length})
              </h3>
              <div className="flex shrink-0 items-center gap-1.5">
                {/* 분할 뷰: 이 페인의 하위 폴더 모두 선택/해제 */}
                {ops.canMutate && onToggleFolderCheck && onToggleAllFolders && (
                  <button
                    onClick={() =>
                      onToggleAllFolders(subFolders, folderSelState !== "all")
                    }
                    className="flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
                  >
                    <span
                      className={`flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold ${
                        folderSelState === "all"
                          ? "bg-blue-600 text-white"
                          : folderSelState === "some"
                            ? "bg-blue-200 text-blue-700"
                            : "bg-slate-200 text-slate-500"
                      }`}
                    >
                      {folderSelState === "some" ? "–" : "✓"}
                    </span>
                    {folderSelState === "all" ? "모두 해제" : "모두 선택"}
                  </button>
                )}
                {/* 정렬: 이름/생성일 × 오름/내림 (persisted) */}
                <select
                  value={folderSort.key}
                  onChange={(e) =>
                    setFolderSort({
                      ...folderSort,
                      key: e.target.value as FolderSortKey,
                    })
                  }
                  title="정렬 기준"
                  className="rounded-md border border-slate-200 bg-white px-1 py-0.5 text-xs text-slate-600"
                >
                  <option value="name">이름순</option>
                  <option value="date">생성일순</option>
                </select>
                <button
                  onClick={() =>
                    setFolderSort({
                      ...folderSort,
                      dir: folderSort.dir === "asc" ? "desc" : "asc",
                    })
                  }
                  title={folderSort.dir === "asc" ? "오름차순" : "내림차순"}
                  className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
                >
                  {folderSort.dir === "asc" ? "↑" : "↓"}
                </button>
                <nav className="flex gap-0.5 rounded-lg bg-slate-100 p-0.5">
                  <button
                    onClick={() => setFolderDisplay("grid")}
                    title="아이콘 보기"
                    className={`rounded-md px-2 py-0.5 text-xs transition-colors ${
                      folderDisplay === "grid"
                        ? "bg-white text-slate-700 shadow-sm"
                        : "text-slate-400 hover:text-slate-600"
                    }`}
                  >
                    ▦
                  </button>
                  <button
                    onClick={() => setFolderDisplay("list")}
                    title="리스트 보기"
                    className={`rounded-md px-2 py-0.5 text-xs transition-colors ${
                      folderDisplay === "list"
                        ? "bg-white text-slate-700 shadow-sm"
                        : "text-slate-400 hover:text-slate-600"
                    }`}
                  >
                    ☰
                  </button>
                </nav>
              </div>
            </div>
            {folderDisplay === "grid" ? (
              <div className="flex flex-wrap gap-1">
                {subFolders.map((f) => (
                  <FolderCard
                    key={f.id}
                    folder={f}
                    count={counts[f.id]}
                    dndPrefix={dndPrefix}
                    dndEnabled={ops.canMutate}
                    onOpen={openFolder}
                    checked={checkedFolderIds?.has(f.id) ?? false}
                    onToggleCheck={ops.canMutate ? onToggleFolderCheck : undefined}
                  />
                ))}
              </div>
            ) : (
              <div className="max-w-2xl divide-y divide-slate-50">
                {subFolders.map((f) => (
                  <FolderRow
                    key={f.id}
                    folder={f}
                    count={counts[f.id]}
                    dndPrefix={dndPrefix}
                    dndEnabled={ops.canMutate}
                    onOpen={openFolder}
                    checked={checkedFolderIds?.has(f.id) ?? false}
                    onToggleCheck={ops.canMutate ? onToggleFolderCheck : undefined}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {/* Photos in the current folder */}
        {current && (
          <section className="py-2">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                사진 {itemsQuery.isPending ? "" : `(${items.length})`}
              </h3>
              {items.length > 0 && (
                <button
                  onClick={() =>
                    useTimelineStore
                      .getState()
                      .setMany(
                        items.map((i) => i.id),
                        photoSelState !== "all",
                      )
                  }
                  className="flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-xs text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700"
                >
                  <span
                    className={`flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold ${
                      photoSelState === "all"
                        ? "bg-blue-600 text-white"
                        : photoSelState === "some"
                          ? "bg-blue-200 text-blue-700"
                          : "bg-slate-200 text-slate-500"
                    }`}
                  >
                    {photoSelState === "some" ? "–" : "✓"}
                  </span>
                  {photoSelState === "all" ? "모두 해제" : "모두 선택"}
                </button>
              )}
            </div>
            {itemsQuery.isPending && (
              <p className="py-6 text-center text-sm text-slate-400">불러오는 중…</p>
            )}
            {itemsQuery.isError && items.length === 0 && (
              <QueryErrorState
                compact
                message="폴더 사진을 불러오지 못했습니다."
                onRetry={() => void itemsQuery.refetch()}
              />
            )}
            {!itemsQuery.isPending && !itemsQuery.isError && items.length === 0 && subFolders.length === 0 && (
              <p className="py-6 text-center text-sm text-slate-400">
                이 폴더는 비어 있습니다.
              </p>
            )}
            {!itemsQuery.isPending && !itemsQuery.isError && items.length === 0 && subFolders.length > 0 && (
              <p className="py-4 text-center text-sm text-slate-400">
                이 폴더에 직접 담긴 사진은 없습니다. 위 하위 폴더를 열어 보세요.
              </p>
            )}
            {/* 행 단위 가상화 — 1000+장 폴더가 셀 전량(각각 dnd 훅)을
             * 마운트하며 얼던 문제 해결. 보이는 행만 마운트한다. */}
            <div ref={marqueeGridRef}>
            <VirtualRows
              count={photoRows.length}
              heightOf={heightOfRow}
              scrollRef={paneScrollRef}
              renderRow={(i) => {
                const row = photoRows[i];
                return (
                  <div style={{ position: "relative", height: row.height }}>
                    {row.cells.map((cell) => (
                      <PhotoCell key={cell.item.id} cell={cell} />
                    ))}
                  </div>
                );
              }}
            />
            </div>
          </section>
        )}

        {!current && subFolders.length === 0 && !subQuery.isPending && !subQuery.isError && (
          <p className="py-10 text-center text-sm text-slate-400">폴더가 없습니다.</p>
        )}
        </div>
        {marquee && (
          <div
            className="pointer-events-none absolute z-30 rounded border border-blue-400 bg-blue-400/10"
            style={{
              left: marquee.left,
              top: marquee.top,
              width: marquee.width,
              height: marquee.height,
            }}
          />
        )}
      </div>
      {captureOpen && captureTarget && canCapture && (
        <CaptureDateDialog
          target={captureTarget}
          onClose={() => setCaptureOpen(false)}
          onDone={() => setCaptureOpen(false)}
        />
      )}
      {auditOpen && ops.canMutate && (
        <FolderNameAuditDialog
          rootId={current?.id ?? null}
          area={area}
          onClose={() => setAuditOpen(false)}
          onDone={() => setAuditOpen(false)}
        />
      )}
    </div>
  );
}

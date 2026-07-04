import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api } from "../api/client";
import type { PhotoFolder } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useFileOps } from "../hooks/useFileOps";
import { useTimelineStore } from "../store/timeline";
import { PhotoCell } from "./timeline/PhotoCell";
import { SPRING_MS, folderBasename } from "./FolderTree";

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
  checked = false,
  onToggleCheck,
}: {
  folder: PhotoFolder;
  count: number | undefined;
  dndPrefix: string;
  onOpen: (f: PhotoFolder) => void;
  checked?: boolean;
  onToggleCheck?: (f: PhotoFolder) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `${dndPrefix}folder:${folder.id}`,
    data: { folderId: folder.id },
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
  checked = false,
  onToggleCheck,
}: {
  folder: PhotoFolder;
  count: number | undefined;
  dndPrefix: string;
  onOpen: (f: PhotoFolder) => void;
  checked?: boolean;
  onToggleCheck?: (f: PhotoFolder) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `${dndPrefix}folder:${folder.id}`,
    data: { folderId: folder.id },
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
}: FolderPaneProps) {
  const current = path.length ? path[path.length - 1] : null;
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const ops = useFileOps();

  const openFolder = (f: PhotoFolder) => onPathChange([...path, f]);
  const jumpTo = (index: number) => onPathChange(path.slice(0, index + 1));

  // 폴더 생성: 현재 위치의 하위로 (루트면 선택 라이브러리의 최상위).
  const onCreateFolder = () => {
    const name = window.prompt(
      current
        ? `'${folderBasename(current.name)}' 아래 새 폴더 이름`
        : "새 폴더 이름 (최상위에 생성)",
    );
    if (!name?.trim()) return;
    const store = useTimelineStore.getState();
    const space = current?.space ?? (store.viewedOwner ? "personal" : store.space);
    ops.createFolder(space, name.trim(), current?.id);
  };

  // 폴더 삭제: 빈 폴더만 (백엔드가 검사 — 사진/하위 폴더 있으면 409 토스트).
  const onRemoveFolder = () => {
    if (!current) return;
    if (
      !window.confirm(
        `'${folderBasename(current.name)}' 폴더를 삭제할까요?\n(빈 폴더만 삭제됩니다 — 사진이 있으면 거부)`,
      )
    )
      return;
    ops.removeFolder(current.space, current.id, () =>
      onPathChange(path.slice(0, -1)),
    );
  };

  // Sub-folders of the current location. At ROOT, only the selected
  // library's top folders show (라이브러리 셀렉터 스코프) — mixing both
  // spaces there was confusing; the other library stays reachable via the
  // collapsed tree section on the left.
  const librarySpace = useTimelineStore((s) =>
    s.viewedOwner ? "personal" : s.space,
  );
  const subQuery = useQuery({
    queryKey: ["folders", current?.id ?? null],
    queryFn: () => api.folders(current?.id),
  });
  const subFolders = (subQuery.data?.folders ?? []).filter(
    (f) => current != null || f.space === librarySpace,
  );

  // Direct photo counts for the visible sub-folders (badge). One batched
  // request per level; failures just hide the badge.
  const countIds = useMemo(() => subFolders.map((f) => f.id), [subFolders]);
  const countsQuery = useQuery({
    queryKey: ["folder-counts", countIds.join(",")],
    queryFn: () => api.folderCounts(countIds),
    enabled: countIds.length > 0,
    staleTime: 30_000,
  });
  const counts = countsQuery.data?.counts ?? {};

  const folderDisplay = useTimelineStore((s) => s.folderDisplay);
  const setFolderDisplay = useTimelineStore((s) => s.setFolderDisplay);

  // Photos directly in the current folder (none at root). Tag each item with
  // the pane's space so thumbnails/ops use the right namespace even when the
  // global scope differs (e.g. personal folder while scope is team).
  const itemsQuery = useQuery({
    queryKey: ["folder-items", current?.id],
    queryFn: () => api.folderItems(current!.id),
    enabled: current != null,
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

  // Background drop target → move into this pane's current folder.
  const bgDrop = useDroppable({
    id: `${dndPrefix}bg`,
    data: current ? { folderId: current.id } : undefined,
    disabled: !dropTarget || !current,
  });

  const gridRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const rows = useMemo(
    () => (width > 0 && items.length > 0 ? layoutBucket("folder", items, width) : []),
    [items, width],
  );

  return (
    <div
      ref={bgDrop.setNodeRef}
      onMouseDownCapture={() => {
        if (!active) onActivate();
      }}
      className={`flex h-full min-w-0 flex-1 flex-col overflow-y-auto transition-colors ${
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
        {/* 폴더 관리: 생성(현재 위치 하위) / 삭제(빈 폴더만) */}
        <span className="ml-auto flex shrink-0 items-center gap-1">
          <button
            onClick={onCreateFolder}
            disabled={ops.isBusy}
            title={current ? "이 폴더 아래 새 폴더" : "최상위에 새 폴더"}
            className="rounded-lg border border-dashed border-slate-300 px-2 py-0.5 text-xs text-slate-500 hover:border-slate-400 hover:text-slate-700 disabled:opacity-40"
          >
            ＋ 새 폴더
          </button>
          {current && (
            <button
              onClick={onRemoveFolder}
              disabled={ops.isBusy}
              title="빈 폴더만 삭제됩니다"
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
        {subFolders.length > 0 && (
          <section className="py-3">
            <div className="mb-1 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {current ? "하위 폴더" : "폴더"} ({subFolders.length})
              </h3>
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
            {folderDisplay === "grid" ? (
              <div className="flex flex-wrap gap-1">
                {subFolders.map((f) => (
                  <FolderCard
                    key={f.id}
                    folder={f}
                    count={counts[f.id]}
                    dndPrefix={dndPrefix}
                    onOpen={openFolder}
                    checked={checkedFolderIds?.has(f.id) ?? false}
                    onToggleCheck={onToggleFolderCheck}
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
                    onOpen={openFolder}
                    checked={checkedFolderIds?.has(f.id) ?? false}
                    onToggleCheck={onToggleFolderCheck}
                  />
                ))}
              </div>
            )}
          </section>
        )}

        {/* Photos in the current folder */}
        {current && (
          <section className="py-2">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              사진 {itemsQuery.isPending ? "" : `(${items.length})`}
            </h3>
            {itemsQuery.isPending && (
              <p className="py-6 text-center text-sm text-slate-400">불러오는 중…</p>
            )}
            {!itemsQuery.isPending && items.length === 0 && subFolders.length === 0 && (
              <p className="py-6 text-center text-sm text-slate-400">
                이 폴더는 비어 있습니다.
              </p>
            )}
            {!itemsQuery.isPending && items.length === 0 && subFolders.length > 0 && (
              <p className="py-4 text-center text-sm text-slate-400">
                이 폴더에 직접 담긴 사진은 없습니다. 위 하위 폴더를 열어 보세요.
              </p>
            )}
            {rows.map(
              (row) =>
                row.kind === "photos" && (
                  <div
                    key={row.key}
                    style={{ position: "relative", height: row.height }}
                  >
                    {row.cells.map((cell) => (
                      <PhotoCell key={cell.item.id} cell={cell} />
                    ))}
                  </div>
                ),
            )}
          </section>
        )}

        {!current && subFolders.length === 0 && !subQuery.isPending && (
          <p className="py-10 text-center text-sm text-slate-400">폴더가 없습니다.</p>
        )}
        </div>
      </div>
    </div>
  );
}

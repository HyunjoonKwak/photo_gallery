import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api } from "../api/client";
import type { PhotoFolder } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";
import { PhotoCell } from "./timeline/PhotoCell";
import { folderBasename } from "./FolderTree";

/** A sub-folder card in the pane — click to drill in, also a drop target.
 * `dndPrefix` keeps droppable ids unique when two panes show the same folder;
 * the real folder id rides along as droppable data (TimelineScreen reads it).
 */
function FolderCard({
  folder,
  dndPrefix,
  onOpen,
}: {
  folder: PhotoFolder;
  dndPrefix: string;
  onOpen: (f: PhotoFolder) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({
    id: `${dndPrefix}folder:${folder.id}`,
    data: { folderId: folder.id },
  });
  return (
    <button
      ref={setNodeRef}
      onClick={() => onOpen(folder)}
      title={folder.name}
      className={`flex w-32 flex-col items-center gap-1 rounded-xl p-3 text-center transition-colors ${
        isOver ? "bg-blue-100 ring-2 ring-blue-400" : "hover:bg-slate-100"
      }`}
    >
      <span className="text-4xl leading-none">📁</span>
      <span className="w-full truncate text-xs text-slate-700">
        {folderBasename(folder.name)}
      </span>
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
}: FolderPaneProps) {
  const current = path.length ? path[path.length - 1] : null;
  const setOrdered = useTimelineStore((s) => s.setOrdered);

  const openFolder = (f: PhotoFolder) => onPathChange([...path, f]);
  const jumpTo = (index: number) => onPathChange(path.slice(0, index + 1));

  // Sub-folders of the current location (root → top-level of both spaces).
  const subQuery = useQuery({
    queryKey: ["folders", current?.id ?? null],
    queryFn: () => api.folders(current?.id),
  });
  const subFolders = subQuery.data?.folders ?? [];

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
      </div>

      <div ref={gridRef} className="flex-1 px-4 pb-10">
        {/* Sub-folders */}
        {subQuery.isPending && (
          <p className="py-6 text-center text-sm text-slate-400">폴더 불러오는 중…</p>
        )}
        {subFolders.length > 0 && (
          <section className="py-3">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {current ? "하위 폴더" : "폴더"} ({subFolders.length})
            </h3>
            <div className="flex flex-wrap gap-1">
              {subFolders.map((f) => (
                <FolderCard
                  key={f.id}
                  folder={f}
                  dndPrefix={dndPrefix}
                  onOpen={openFolder}
                />
              ))}
            </div>
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
  );
}

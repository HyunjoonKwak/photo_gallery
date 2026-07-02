import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api } from "../api/client";
import type { PhotoFolder } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { PhotoCell } from "./timeline/PhotoCell";
import { FolderTree, folderBasename } from "./FolderTree";

/** A sub-folder card in the main pane — click to drill in, also a drop target. */
function FolderCard({
  folder,
  onOpen,
}: {
  folder: PhotoFolder;
  onOpen: (f: PhotoFolder) => void;
}) {
  const { isOver, setNodeRef } = useDroppable({ id: `folder:${folder.id}` });
  return (
    <button
      ref={setNodeRef}
      onClick={() => onOpen(folder)}
      title={folder.name}
      className={`flex w-32 flex-col items-center gap-1 rounded-xl p-3 text-center transition-colors ${
        isOver
          ? "bg-blue-100 ring-2 ring-blue-400"
          : "hover:bg-slate-100"
      }`}
    >
      <span className="text-4xl leading-none">📁</span>
      <span className="w-full truncate text-xs text-slate-700">
        {folderBasename(folder.name)}
      </span>
    </button>
  );
}

/** Folder view (spec 9.3): lazy folder tree on the left for quick jumps, and a
 * Finder-style main pane that shows the current folder's sub-folders (click to
 * drill in) plus its photos, with a breadcrumb path. Both spaces' top-level
 * folders are the starting point.
 */
export function FolderView() {
  // Navigation path (breadcrumb). Empty = root (both spaces' top folders).
  const [path, setPath] = useState<PhotoFolder[]>([]);
  const current = path.length ? path[path.length - 1] : null;
  const ops = useFileOps();
  const setOrdered = useTimelineStore((s) => s.setOrdered);

  const openFolder = (f: PhotoFolder) => setPath((p) => [...p, f]);
  const jumpTo = (index: number) => setPath((p) => p.slice(0, index + 1));
  const goRoot = () => setPath([]);

  // Sub-folders of the current location (root → top-level of both spaces).
  const subQuery = useQuery({
    queryKey: ["folders", current?.id ?? null],
    queryFn: () => api.folders(current?.id),
  });
  const subFolders = subQuery.data?.folders ?? [];

  // Photos directly in the current folder (none at root).
  const itemsQuery = useQuery({
    queryKey: ["folder-items", current?.id],
    queryFn: () => api.folderItems(current!.id),
    enabled: current != null,
  });
  const items = useMemo(() => itemsQuery.data?.items ?? [], [itemsQuery.data]);

  useEffect(() => {
    setOrdered(items);
  }, [items, setOrdered]);

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

  const onCreateFolder = () => {
    const name = window.prompt("새 폴더 이름 (공용 최상위에 생성)");
    if (name?.trim()) ops.createFolder(current?.space ?? "team", name.trim());
  };

  return (
    <div className="flex h-full">
      {/* Left: quick-jump tree. Selecting resets the breadcrumb to that folder. */}
      <aside
        data-no-boxselect
        className="w-60 shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2"
      >
        <button
          onClick={onCreateFolder}
          className="mx-2 mt-1 mb-1 w-[calc(100%-1rem)] rounded-lg border border-dashed border-slate-300 px-2 py-1.5 text-sm text-slate-500 hover:border-slate-400 hover:text-slate-700"
        >
          + 새 폴더
        </button>
        <h4 className="px-2 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
          공용 폴더
        </h4>
        <FolderTree
          space="team"
          droppable
          selectedId={current?.id}
          onSelect={(f) => setPath([f])}
        />
        <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
          내 개인 폴더
        </h4>
        <FolderTree
          space="personal"
          droppable
          selectedId={current?.id}
          onSelect={(f) => setPath([f])}
        />
      </aside>

      {/* Right: Finder-style — breadcrumb + sub-folders + photos */}
      <main className="min-w-0 flex-1 overflow-y-auto">
        {/* Breadcrumb */}
        <div
          data-no-boxselect
          className="sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b border-slate-100 bg-white/90 px-4 py-2 text-sm backdrop-blur"
        >
          <button
            onClick={goRoot}
            className={`rounded px-1.5 py-0.5 ${current ? "text-blue-600 hover:bg-slate-100" : "font-semibold text-slate-700"}`}
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

        <div ref={gridRef} className="px-4 pb-10">
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
                  <FolderCard key={f.id} folder={f} onOpen={openFolder} />
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
            <p className="py-10 text-center text-sm text-slate-400">
              폴더가 없습니다.
            </p>
          )}
        </div>
      </main>
    </div>
  );
}

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api } from "../api/client";
import type { PhotoFolder } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { PhotoCell } from "./timeline/PhotoCell";

/** Folder view (spec 9.3): folder list on the left, that folder's photos on
 * the right as a justified grid. The list doubles as drop targets, so photos
 * can be dragged between folders here too. Folder contents are modest in
 * size, so the grid renders without virtualization.
 */
function FolderListRow({
  folder,
  selected,
  onSelect,
}: {
  folder: PhotoFolder;
  selected: boolean;
  onSelect: () => void;
}) {
  const { isOver, setNodeRef } = useDroppable({ id: `folder:${folder.id}` });
  return (
    <li ref={setNodeRef}>
      <button
        onClick={onSelect}
        className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors ${
          isOver
            ? "bg-blue-100 text-blue-800 ring-2 ring-blue-400"
            : selected
              ? "bg-slate-200 font-medium text-slate-800"
              : "text-slate-700 hover:bg-slate-100"
        }`}
      >
        <span aria-hidden>📁</span>
        <span className="truncate">{folder.name}</span>
      </button>
    </li>
  );
}

export function FolderView() {
  const foldersQuery = useQuery({ queryKey: ["folders"], queryFn: api.folders });
  const folders = useMemo(
    () => foldersQuery.data?.folders ?? [],
    [foldersQuery.data],
  );
  const [folderId, setFolderId] = useState<string | null>(null);
  const ops = useFileOps();
  const setOrdered = useTimelineStore((s) => s.setOrdered);

  // Default to the first folder once loaded.
  useEffect(() => {
    if (!folderId && folders.length > 0) setFolderId(folders[0].id);
  }, [folders, folderId]);

  const itemsQuery = useQuery({
    queryKey: ["folder-items", folderId],
    queryFn: () => api.folderItems(folderId!),
    enabled: folderId != null,
  });
  const items = useMemo(
    () => itemsQuery.data?.items ?? [],
    [itemsQuery.data],
  );

  // Register display order for lightbox stepping / shift ranges in this view.
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

  const team = folders.filter((f) => f.space === "team");
  const personal = folders.filter((f) => f.space === "personal");
  const current = folders.find((f) => f.id === folderId) ?? null;

  const onCreateFolder = () => {
    const name = window.prompt("새 폴더 이름을 입력하세요");
    if (name?.trim()) {
      ops.createFolder(current?.space ?? "team", name.trim());
    }
  };

  const group = (label: string, list: PhotoFolder[]) => (
    <div key={label}>
      <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </h4>
      <ul className="space-y-0.5">
        {list.map((f) => (
          <FolderListRow
            key={f.id}
            folder={f}
            selected={f.id === folderId}
            onSelect={() => setFolderId(f.id)}
          />
        ))}
      </ul>
    </div>
  );

  return (
    <div className="flex h-full">
      <aside
        data-no-boxselect
        className="w-56 shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2"
      >
        <button
          onClick={onCreateFolder}
          className="mx-2 mt-1 w-[calc(100%-1rem)] rounded-lg border border-dashed border-slate-300 px-2 py-1.5 text-sm text-slate-500 hover:border-slate-400 hover:text-slate-700"
        >
          + 새 폴더
        </button>
        {group("공용 폴더", team)}
        {group("내 개인 폴더", personal)}
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-700">
            {current ? `${current.name} · ${items.length}장` : "폴더를 선택하세요"}
          </h2>
        </div>
        <div ref={gridRef} className="px-4 pb-8">
          {itemsQuery.isPending && folderId && (
            <p className="py-8 text-center text-sm text-slate-400">불러오는 중…</p>
          )}
          {!itemsQuery.isPending && items.length === 0 && folderId && (
            <p className="py-8 text-center text-sm text-slate-400">
              폴더가 비어 있습니다. 타임라인에서 사진을 끌어다 놓아보세요.
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
        </div>
      </main>
    </div>
  );
}

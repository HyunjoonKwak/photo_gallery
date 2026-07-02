import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoFolder } from "../api/types";
import { layoutBucket } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { PhotoCell } from "./timeline/PhotoCell";
import { FolderTree, folderBasename } from "./FolderTree";

/** Folder view (spec 9.3): lazy folder tree on the left (selectable + drop
 * target), the selected folder's photos as a justified grid on the right.
 */
export function FolderView() {
  const [folder, setFolder] = useState<PhotoFolder | null>(null);
  const ops = useFileOps();
  const setOrdered = useTimelineStore((s) => s.setOrdered);

  const itemsQuery = useQuery({
    queryKey: ["folder-items", folder?.id],
    queryFn: () => api.folderItems(folder!.id),
    enabled: folder != null,
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
    if (name?.trim()) ops.createFolder(folder?.space ?? "team", name.trim());
  };

  return (
    <div className="flex h-full">
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
          selectedId={folder?.id}
          onSelect={setFolder}
        />
        <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
          내 개인 폴더
        </h4>
        <FolderTree
          space="personal"
          droppable
          selectedId={folder?.id}
          onSelect={setFolder}
        />
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <div className="px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-700">
            {folder
              ? `${folderBasename(folder.name)} · ${items.length}장`
              : "폴더를 선택하세요"}
          </h2>
        </div>
        <div ref={gridRef} className="px-4 pb-8">
          {itemsQuery.isPending && folder && (
            <p className="py-8 text-center text-sm text-slate-400">불러오는 중…</p>
          )}
          {!itemsQuery.isPending && folder && items.length === 0 && (
            <p className="py-8 text-center text-sm text-slate-400">
              이 폴더에 직접 속한 사진이 없습니다. (하위 폴더는 왼쪽에서 펼쳐보세요)
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

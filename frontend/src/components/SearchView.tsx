import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { libraryLabel } from "../lib/library";
import { layoutBucket } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";
import { PhotoCell } from "./timeline/PhotoCell";

/** Search results view: DSM's own index (filename/folder/tag — 실 NAS 검증).
 * Results feed the shared selection model, so the existing action bar / DnD /
 * lightbox / bulk progress all work on them unchanged.
 */
export function SearchView() {
  const space = useTimelineStore((s) => s.space);
  const query = useTimelineStore((s) => s.searchQuery);
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const replaceSelection = useTimelineStore((s) => s.replaceSelection);
  const setManageTab = useTimelineStore((s) => s.setManageTab);

  const resultQuery = useQuery({
    queryKey: ["search", space, query],
    queryFn: () => api.searchPhotos(space, query),
    enabled: query.trim().length > 0,
    staleTime: 60_000,
  });
  const items = useMemo(
    () => (resultQuery.data?.items ?? []).map((it) => ({ ...it, space })),
    [resultQuery.data, space],
  );
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
    () => (width > 0 && items.length > 0 ? layoutBucket("search", items, width) : []),
    [items, width],
  );

  return (
    <div className="h-full overflow-y-auto">
      <div
        data-no-boxselect
        className="sticky top-0 z-10 flex flex-wrap items-center gap-2 border-b border-slate-100 bg-white/90 px-4 py-2 text-sm backdrop-blur"
      >
        <span className="font-semibold text-slate-800">
          🔍 "{query}" 검색 결과
          {!resultQuery.isPending && ` (${items.length.toLocaleString()}장)`}
        </span>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
          {libraryLabel(space, useTimelineStore.getState().viewedOwner)}
        </span>
        <button
          onClick={() => replaceSelection(items.map((i) => i.id))}
          disabled={items.length === 0}
          className="rounded-lg border border-blue-200 px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 disabled:opacity-40"
        >
          전체 선택
        </button>
        <span className="hidden text-xs text-slate-400 sm:inline">
          파일명·폴더명·태그 기준 · 선택 후 액션바/드래그로 정리
        </span>
        <button
          onClick={() => setManageTab("folders")}
          className="ml-auto rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
        >
          ✕ 닫기
        </button>
      </div>

      <div className="px-4 pb-10">
        <div ref={gridRef}>
          {resultQuery.isPending && query && (
            <p className="py-10 text-center text-sm text-slate-400">검색 중…</p>
          )}
          {resultQuery.isError && (
            <p className="py-10 text-center text-sm text-red-500">
              검색에 실패했습니다.
            </p>
          )}
          {!resultQuery.isPending && !resultQuery.isError && items.length === 0 && (
            <p className="py-10 text-center text-sm text-slate-400">
              "{query}"에 해당하는 사진이 없습니다.
            </p>
          )}
          <div className="py-3">
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
        </div>
      </div>
    </div>
  );
}

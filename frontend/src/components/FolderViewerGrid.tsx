import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoFolder, PhotoItem } from "../api/types";
import { useTimelineStore } from "../store/timeline";
import { Thumb } from "./timeline/Thumb";
import { folderBasename } from "./FolderTree";
import { VirtualRows } from "./VirtualRows";

/** 사진 뷰어의 폴더 줌 — 폴더 구조를 그대로 탐색(순수 뷰어). 폴더 카드에 직속
 * 사진 4장 미리보기, 클릭하면 한 depth 진입. 리프 폴더의 사진은 썸네일 그리드
 * 로, 탭하면 라이트박스. 이동/삭제 없음(정리는 폴더 분류에서). */
export function FolderViewerGrid() {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const librarySpace = useTimelineStore((s) => s.space);
  const registerBack = useTimelineStore((s) => s.registerBack);
  const setScreenBackDepth = useTimelineStore((s) => s.setScreenBackDepth);
  const [path, setPath] = useState<PhotoFolder[]>([]);
  const current = path.length ? path[path.length - 1] : null;

  // 폴더 안에 들어가 있으면 "뒤로"가 한 단계 상위 폴더로.
  useEffect(() => {
    if (path.length === 0) return;
    return registerBack(() => setPath((p) => p.slice(0, -1)));
  }, [path.length, registerBack]);
  // 뒤로 깊이 보고(히스토리 미러링용). 언마운트 시 0으로 리셋.
  useEffect(() => {
    setScreenBackDepth(path.length);
  }, [path.length, setScreenBackDepth]);
  useEffect(() => () => setScreenBackDepth(0), [setScreenBackDepth]);

  const subQuery = useQuery({
    queryKey: ["folders", current?.id ?? null],
    queryFn: () => api.folders(current?.id),
  });
  // 루트: 선택 라이브러리(공용/내사진)의 최상위(parent_id 없는) 폴더만.
  // (folders(없음) 호출은 전체 flat을 주므로 뷰어에서 최상위로 좁힌다.)
  // 하위 진입 시엔 folders(current.id)가 이미 직속 자식만 반환.
  const subFolders = (subQuery.data?.folders ?? []).filter((f) =>
    current != null ? true : f.parent_id == null && f.space === librarySpace,
  );

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

  const open = (f: PhotoFolder) => setPath((p) => [...p, f]);
  const jumpTo = (i: number) => setPath((p) => p.slice(0, i + 1));

  return (
    <div className="flex h-full flex-col">
      {/* 브레드크럼 */}
      <div className="flex shrink-0 flex-wrap items-center gap-1 border-b border-slate-100 bg-white px-4 py-1.5 text-sm">
        <button
          onClick={() => setPath([])}
          className={`rounded px-1.5 py-0.5 ${
            current
              ? "text-blue-600 hover:bg-slate-100"
              : "font-semibold text-slate-700"
          }`}
        >
          🗂 폴더
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

      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {subQuery.isPending && (
          <p className="p-6 text-center text-sm text-slate-400">
            폴더 불러오는 중…
          </p>
        )}

        {/* 하위 폴더 카드 (미리보기 4장) */}
        {subFolders.length > 0 && (
          <div className="p-4">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              {current ? "하위 폴더" : "폴더"} ({subFolders.length})
            </h3>
            <div
              className="grid gap-3"
              style={{
                gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
              }}
            >
              {subFolders.map((f) => (
                <FolderCard key={f.id} folder={f} onOpen={() => open(f)} />
              ))}
            </div>
          </div>
        )}

        {/* 현재 폴더 직속 사진 */}
        {current && (
          <FolderPhotos
          scrollRef={scrollRef} items={items} pending={itemsQuery.isPending} hasSub={subFolders.length > 0} />
        )}

        {!current && !subQuery.isPending && subFolders.length === 0 && (
          <p className="p-10 text-center text-sm text-slate-400">폴더가 없습니다.</p>
        )}
      </div>
    </div>
  );
}

/** 폴더 카드 — 직속 사진 4장을 2×2 미리보기로. */
function FolderCard({
  folder,
  onOpen,
}: {
  folder: PhotoFolder;
  onOpen: () => void;
}) {
  // 미리보기 4장만 필요 → limit로 한 페이지만(폴더 전체 목록을 안 받음).
  // 전체 목록(folder-items)과 캐시 키 분리(folder-preview).
  const q = useQuery({
    queryKey: ["folder-preview", folder.id],
    queryFn: () => api.folderItems(folder.id, 8),
    staleTime: 5 * 60_000,
  });
  const preview = (q.data?.items ?? []).slice(0, 4);
  return (
    <button
      onClick={onOpen}
      title={folder.name}
      className="group flex flex-col gap-1.5 rounded-xl p-2 text-left hover:bg-slate-100"
    >
      <div className="grid aspect-square grid-cols-2 grid-rows-2 gap-0.5 overflow-hidden rounded-lg bg-slate-200">
        {preview.length === 0 ? (
          <div className="col-span-2 row-span-2 flex items-center justify-center text-4xl">
            📁
          </div>
        ) : (
          Array.from({ length: 4 }, (_, i) =>
            preview[i] ? (
              <Thumb key={i} item={preview[i]} space={folder.space} rounded="" />
            ) : (
              <div key={i} className="bg-slate-100" />
            ),
          )
        )}
      </div>
      <span className="truncate px-0.5 text-xs font-medium text-slate-700">
        {folderBasename(folder.name)}
      </span>
    </button>
  );
}

function FolderPhotos({
  items,
  pending,
  hasSub,
  scrollRef,
}: {
  items: PhotoItem[];
  pending: boolean;
  hasSub: boolean;
  scrollRef: React.RefObject<HTMLDivElement | null>;
}) {
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const openLightbox = useTimelineStore((s) => s.openLightbox);
  useEffect(() => {
    if (items.length) setOrdered(items);
  }, [items, setOrdered]);

  // 폭 프로브 → 열 수/행 높이(정사각: 타일 한 변 + gap 4px).
  const probeRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = probeRef.current;
    if (!el) return;
    setWidth(Math.floor(el.clientWidth)); // 초기 폭 동기 측정(RO 초기 전달 미보장)
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [pending, items.length]);
  const cols = Math.max(1, Math.floor((width + 4) / (116 + 4)));
  const rowCount = Math.ceil(items.length / cols);
  const tile = width > 0 ? (width - (cols - 1) * 4) / cols : 0;
  const heightOfRow = useCallback(() => tile + 4, [tile]);

  if (pending)
    return <p className="p-6 text-center text-sm text-slate-400">불러오는 중…</p>;
  if (items.length === 0)
    return (
      <p className="p-6 text-center text-sm text-slate-400">
        {hasSub
          ? "이 폴더에 직접 담긴 사진은 없습니다. 위 하위 폴더를 열어 보세요."
          : "이 폴더는 비어 있습니다."}
      </p>
    );
  return (
    <div className="px-4 pb-4">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        사진 ({items.length})
      </h3>
      {/* 부모 스크롤에 얹는 정사각 그리드 — 행 단위 가상화(1000+장 폴더 대비). */}
      <div ref={probeRef}>
        <VirtualRows
          count={rowCount}
          heightOf={heightOfRow}
          scrollRef={scrollRef}
          renderRow={(r) => (
            <div
              className="grid gap-1 pb-1"
              style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
            >
              {items.slice(r * cols, r * cols + cols).map((it) => (
                <button
                  key={it.id}
                  data-photo-id={it.id}
                  onClick={() => openLightbox(it.id)}
                  className="aspect-square overflow-hidden rounded-sm outline-none"
                >
                  <Thumb item={it} space={it.space} />
                </button>
              ))}
            </div>
          )}
        />
      </div>
    </div>
  );
}

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { PhotoItem, Space } from "../../api/types";
import { useTimelineStore } from "../../store/timeline";
import { Thumb } from "./Thumb";

/** 균일 정사각 사진 그리드 + 행 가상화 (큰 목록 대비). 클릭=라이트박스로 열고,
 * 목록을 setOrdered 해 좌우 넘기기가 그 그룹 안에서 순회한다. 사진 뷰어 일 뷰와
 * 앨범(인물/장소/비디오) 그룹이 공유하는 순수 뷰어 그리드. */
export function UniformPhotoGrid({
  items,
  space,
  minTile = 116,
  gap = 4,
}: {
  items: PhotoItem[];
  space?: Space;
  minTile?: number;
  gap?: number;
}) {
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const openLightbox = useTimelineStore((s) => s.openLightbox);

  useEffect(() => {
    setOrdered(items);
  }, [items, setOrdered]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const cols = Math.max(1, Math.floor((width + gap) / (minTile + gap)));
  const tile = cols > 0 ? (width - gap * (cols - 1)) / cols : minTile;
  const rowCount = Math.ceil(items.length / cols);

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => tile + gap,
    overscan: 6,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [tile, rowCount, virtualizer]);

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto p-1">
      <div
        style={{
          height: virtualizer.getTotalSize(),
          position: "relative",
          width: "100%",
        }}
      >
        {virtualizer.getVirtualItems().map((row) => {
          const start = row.index * cols;
          const rowItems = items.slice(start, start + cols);
          return (
            <div
              key={row.key}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${row.start}px)`,
                display: "flex",
                gap,
              }}
            >
              {rowItems.map((it) => (
                <button
                  key={it.id}
                  data-photo-id={it.id}
                  onClick={() => openLightbox(it.id)}
                  style={{ width: tile, height: tile }}
                  className="overflow-hidden rounded-sm outline-none"
                >
                  <Thumb item={it} space={space} />
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

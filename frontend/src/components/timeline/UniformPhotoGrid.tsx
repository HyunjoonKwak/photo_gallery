import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { PhotoItem, Space } from "../../api/types";
import { useTimelineStore } from "../../store/timeline";
import { useScrollMetrics } from "../../hooks/useScrollMetrics";
import { isMonthOrdered, uniformMonthMarkers } from "../../lib/scrubberMarkers";
import { Thumb } from "./Thumb";
import { Scrubber } from "./Scrubber";

/** 균일 정사각 사진 그리드 + 행 가상화 (큰 목록 대비). 클릭=라이트박스로 열고,
 * 목록을 setOrdered 해 좌우 넘기기가 그 그룹 안에서 순회한다. 사진 뷰어 일 뷰와
 * 앨범(인물/장소/비디오) 그룹이 공유하는 순수 뷰어 그리드.
 *
 * 목록이 촬영일순이면 우측에 날짜 스크러버를 단다. 아니면(앨범 — 사람이 정한
 * 순서) 레일 대신 늘 보이는 가는 스크롤바를 둔다. 레일을 달면 연·월 라벨이
 * 실제 순서와 어긋나 거짓말이 된다. */
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

  const { ref: scrollRef, setRef, el, viewportH, scrollTop, onScroll } =
    useScrollMetrics();
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    if (!el) return;
    setWidth(Math.floor(el.clientWidth));
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);

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

  // 레일은 목록이 시간순일 때만. 판정은 목록이 바뀔 때 한 번만 돈다.
  const monthOrdered = useMemo(() => isMonthOrdered(items), [items]);
  const markers = useMemo(
    () => (monthOrdered ? uniformMonthMarkers(items, cols, tile + gap) : []),
    [monthOrdered, items, cols, tile, gap],
  );

  return (
    <div className="relative h-full">
      <div
        ref={setRef}
        onScroll={onScroll}
        className={`h-full overflow-y-auto p-1 ${markers.length ? "" : "scroll-thin"}`}
      >
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
      {markers.length > 0 && (
        <Scrubber
          markers={markers}
          totalHeight={virtualizer.getTotalSize()}
          viewportHeight={viewportH}
          scrollTop={scrollTop}
          onJump={(offset) => {
            const node = scrollRef.current;
            if (node) node.scrollTop = offset;
          }}
        />
      )}
    </div>
  );
}

import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import type { PhotoItem, Space } from "../../api/types";
import { useTimelineStore } from "../../store/timeline";
import { useScrollMetrics } from "../../hooks/useScrollMetrics";
import { layoutMasonry, visibleCells } from "../../lib/masonry";
import { isMonthOrdered } from "../../lib/scrubberMarkers";
import { Thumb } from "./Thumb";
import { Scrubber, type ScrubberMarker } from "./Scrubber";

const MIN_COLUMN = 116;
const GAP = 4;

/** 메이슨리 사진 그리드 — 열 폭은 같고 높이는 사진 비율대로.
 *
 * 정사각 그리드(`UniformPhotoGrid`)가 세로 사진의 위아래를 잘라 내는 것을
 * 싫어하는 사람을 위한 배치. 행이 없어 행 단위 가상화를 못 쓰므로 배치를
 * 고정 높이 띠로 색인해 두고(`lib/masonry`) 보이는 띠만 그린다. */
export function MasonryPhotoGrid({
  items,
  space,
}: {
  items: PhotoItem[];
  space?: Space;
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

  // 폭이 바뀔 때만 다시 배치한다 — 스크롤은 배치를 건드리지 않는다.
  const layout = useMemo(
    () => layoutMasonry(items, width - GAP * 2, MIN_COLUMN, GAP),
    [items, width],
  );
  const visible = useMemo(
    () => visibleCells(layout, scrollTop, viewportH),
    [layout, scrollTop, viewportH],
  );

  // 레일은 목록이 시간순일 때만 — 앨범(사람이 정한 순서)에는 달지 않는다.
  const monthOrdered = useMemo(() => isMonthOrdered(items), [items]);
  const markers = useMemo<ScrubberMarker[]>(() => {
    if (!monthOrdered) return [];
    const out: ScrubberMarker[] = [];
    let last = "";
    for (const cell of layout.cells) {
      const month = cell.item.taken_at.slice(0, 7);
      if (month === last) continue;
      last = month;
      out.push({ month, offset: cell.top });
    }
    return out;
  }, [monthOrdered, layout]);

  return (
    <div className="relative h-full">
      <div
        ref={setRef}
        onScroll={onScroll}
        className={`h-full overflow-y-auto p-1 ${markers.length ? "" : "scroll-thin"}`}
      >
        <div style={{ height: layout.height, position: "relative" }}>
          {visible.map((i) => {
            const cell = layout.cells[i];
            return (
              <button
                key={cell.item.id}
                data-photo-id={cell.item.id}
                onClick={() => openLightbox(cell.item.id)}
                style={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  width: cell.width,
                  height: cell.height,
                  transform: `translate(${cell.left}px, ${cell.top}px)`,
                }}
                className="overflow-hidden rounded-sm outline-none"
              >
                <Thumb item={cell.item} space={space} />
              </button>
            );
          })}
        </div>
      </div>
      {markers.length > 0 && (
        <Scrubber
          markers={markers}
          totalHeight={layout.height}
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

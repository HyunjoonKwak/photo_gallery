import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { PhotoItem, Space } from "../../api/types";
import { formatDayHeader } from "../../lib/dates";
import { useTimelineStore } from "../../store/timeline";
import { Thumb } from "./Thumb";
import { Scrubber, type ScrubberMarker } from "./Scrubber";

const HEADER_H = 40;
const GAP = 4;
const MIN_TILE = 116;

type Row =
  | { kind: "header"; key: string; day: string; label: string }
  | { kind: "photos"; key: string; day: string; items: PhotoItem[] };

/** 이미 전량 로드된 아이템 목록을 일자별 헤더 + 썸네일 바둑판으로(행 가상화)
 * 보여주고 우측 날짜 스크러버(연·월)를 단다. 탭=라이트박스. 비디오 탭처럼
 * "필터된 목록"을 감상용 타임라인으로 뿌릴 때 쓴다(사진 뷰어의 일 뷰는
 * buckets 기반 지연 로드라 별도). 목록은 최신순 전제. */
export function DateGroupedGrid({
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

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const setScrollRefs = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    setScrollEl(el);
  }, []);
  const [contentEl, setContentEl] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  useLayoutEffect(() => {
    if (!scrollEl) return;
    const ro = new ResizeObserver(() => setViewportH(scrollEl.clientHeight));
    ro.observe(scrollEl);
    return () => ro.disconnect();
  }, [scrollEl]);
  useLayoutEffect(() => {
    if (!contentEl) return;
    const ro = new ResizeObserver(() =>
      setWidth(Math.floor(contentEl.clientWidth)),
    );
    ro.observe(contentEl);
    return () => ro.disconnect();
  }, [contentEl]);
  const cols = Math.max(1, Math.floor((width + GAP) / (MIN_TILE + GAP)));
  const tile = cols > 0 ? (width - GAP * (cols - 1)) / cols : MIN_TILE;

  // 일자별 그룹 (목록이 최신순이므로 삽입 순서가 곧 최신순).
  const groups = useMemo(() => {
    const m = new Map<string, PhotoItem[]>();
    for (const it of items) {
      const day = it.taken_at.slice(0, 10);
      const list = m.get(day);
      if (list) list.push(it);
      else m.set(day, [it]);
    }
    return [...m.entries()];
  }, [items]);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    for (const [day, dayItems] of groups) {
      out.push({ kind: "header", key: `h-${day}`, day, label: formatDayHeader(day) });
      for (let i = 0; i < Math.ceil(dayItems.length / cols); i++) {
        out.push({
          kind: "photos",
          key: `p-${day}-${i}`,
          day,
          items: dayItems.slice(i * cols, i * cols + cols),
        });
      }
    }
    return out;
  }, [groups, cols]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => (rows[i]?.kind === "header" ? HEADER_H : tile + GAP),
    overscan: 8,
    getItemKey: (i) => rows[i]?.key ?? i,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [rows, tile, virtualizer]);

  // 스크러버 월 마커: 헤더 행의 콘텐츠 offset(가상화 실측), 월 단위 중복 제거.
  const totalSize = virtualizer.getTotalSize();
  const markers = useMemo<ScrubberMarker[]>(() => {
    const out: ScrubberMarker[] = [];
    let last = "";
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.kind !== "header") continue;
      const month = r.day.slice(0, 7);
      if (month === last) continue;
      last = month;
      const off = virtualizer.getOffsetForIndex(i, "start");
      const offset =
        typeof off === "number" ? off : Array.isArray(off) ? off[0] : 0;
      out.push({ month, offset });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, totalSize, viewportH]);

  if (items.length === 0)
    return <p className="p-6 text-sm text-slate-400">비디오가 없습니다.</p>;

  return (
    <div className="relative h-full">
      <div
        ref={setScrollRefs}
        className="h-full overflow-y-auto"
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        <div className="pl-3 pr-12">
          <div
            ref={setContentEl}
            style={{
              height: virtualizer.getTotalSize(),
              position: "relative",
              width: "100%",
            }}
          >
            {virtualizer.getVirtualItems().map((v) => {
              const row = rows[v.index];
              if (!row) return null;
              return (
                <div
                  key={v.key}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${v.start}px)`,
                  }}
                >
                  {row.kind === "header" ? (
                    <div className="flex items-end px-2 pb-1 pt-3 text-sm font-semibold text-slate-700">
                      {row.label}
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: GAP }}>
                      {row.items.map((it) => (
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
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <Scrubber
        markers={markers}
        totalHeight={totalSize}
        viewportHeight={viewportH}
        scrollTop={scrollTop}
        onJump={(offset) => {
          const el = scrollRef.current;
          if (el) el.scrollTop = offset;
        }}
      />
    </div>
  );
}

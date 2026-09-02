import { useEffect, useRef, useState } from "react";
import { formatMonth } from "../../lib/dates";
import { useTimelineStore } from "../../store/timeline";

export interface ScrubberMarker {
  /** YYYY-MM */
  month: string;
  offset: number;
}

/** Right-edge date scrubber (IMPROVEMENTS B-1): month markers positioned by
 * content offset — possible because count-first buckets give the full-archive
 * height up front. Dragging jumps anywhere; a bubble shows the target month.
 */
export function Scrubber({
  markers,
  totalHeight,
  viewportHeight,
  scrollTop,
  onJump,
}: {
  markers: ScrubberMarker[];
  totalHeight: number;
  viewportHeight: number;
  scrollTop: number;
  onJump: (offset: number) => void;
}) {
  const railRef = useRef<HTMLDivElement>(null);
  const [dragMonth, setDragMonth] = useState<string | null>(null);

  // 스크러버가 실제로 그려질 때만 store에 보고 — NavControls가 레일 자리를
  // 피해 왼쪽으로 이동한다(연/월 라벨·버튼 겹침 방지).
  const visible = viewportHeight > 0 && totalHeight > viewportHeight;
  const scrubberMounted = useTimelineStore((s) => s.scrubberMounted);
  const scrubberUnmounted = useTimelineStore((s) => s.scrubberUnmounted);
  useEffect(() => {
    if (!visible) return;
    scrubberMounted();
    return () => scrubberUnmounted();
  }, [visible, scrubberMounted, scrubberUnmounted]);

  if (!visible) return null;

  const railH = viewportHeight;
  const thumbH = 32;
  const scrollRange = Math.max(0, totalHeight - viewportHeight);
  const thumbTravel = Math.max(0, railH - thumbH);
  const thumbY =
    scrollRange > 0
      ? Math.min(1, Math.max(0, scrollTop / scrollRange)) * thumbTravel
      : 0;

  const monthAt = (offset: number): string => {
    let current = markers[0]?.month ?? "";
    for (const m of markers) {
      if (m.offset <= offset) current = m.month;
      else break;
    }
    return current;
  };
  const activeMonth = monthAt(scrollTop);
  let activeIndex = 0;
  for (let i = 0; i < markers.length; i += 1) {
    if (markers[i].offset <= scrollTop) activeIndex = i;
    else break;
  }
  const jumpToIndex = (index: number) => {
    const next = Math.min(markers.length - 1, Math.max(0, index));
    const marker = markers[next];
    if (marker) onJump(marker.offset);
  };

  const handlePointer = (e: React.PointerEvent) => {
    const rail = railRef.current;
    if (!rail) return;
    const rect = rail.getBoundingClientRect();
    const travel = Math.max(1, rect.height - thumbH);
    const ratio = Math.min(
      1,
      Math.max(0, (e.clientY - rect.top - thumbH / 2) / travel),
    );
    const offset = ratio * scrollRange;
    setDragMonth(monthAt(offset));
    onJump(offset);
  };

  // 텍스트는 좁은 레일에 맞춰 충돌하는 것만 생략하되, 아래에서 모든 월을
  // 눈금으로 따로 그린다. 예전 26px 단일 간격은 19년/모바일 높이에서 연도
  // 주위가 전부 예약돼 월 라벨을 0개로 만들었다.
  const YEAR_GAP = 22;
  const LABEL_GAP = 12;
  const railYOf = (m: ScrubberMarker) => (m.offset / totalHeight) * railH;
  type RailLabel = { key: string; y: number; text: string; kind: "year" | "month" };
  const placed: RailLabel[] = [];
  const seenYears = new Set<string>();
  for (const m of markers) {
    const year = m.month.slice(0, 4);
    if (seenYears.has(year)) continue;
    seenYears.add(year);
    const y = railYOf(m);
    if (!placed.length || y - placed[placed.length - 1].y >= YEAR_GAP) {
      placed.push({ key: `y-${m.month}`, y, text: year, kind: "year" });
    }
  }
  for (const m of markers) {
    const y = railYOf(m);
    if (placed.every((p) => Math.abs(p.y - y) >= LABEL_GAP)) {
      placed.push({
        key: `m-${m.month}`,
        y,
        text: `${Number(m.month.slice(5, 7))}월`,
        kind: "month",
      });
    }
  }
  placed.sort((a, b) => a.y - b.y);

  return (
    <div
      ref={railRef}
      data-no-boxselect
      role="slider"
      tabIndex={0}
      aria-label="날짜 스크러버"
      aria-orientation="vertical"
      aria-valuemin={0}
      aria-valuemax={Math.max(0, markers.length - 1)}
      aria-valuenow={activeIndex}
      aria-valuetext={activeMonth ? formatMonth(`${activeMonth}-01`) : undefined}
      title="드래그하거나 위·아래 방향키로 월 이동"
      className="absolute right-0 top-0 z-30 h-full w-10 cursor-row-resize select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-400"
      onKeyDown={(e) => {
        let next: number | null = null;
        if (e.key === "ArrowDown") next = activeIndex + 1;
        else if (e.key === "ArrowUp") next = activeIndex - 1;
        else if (e.key === "PageDown") next = activeIndex + 3;
        else if (e.key === "PageUp") next = activeIndex - 3;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = markers.length - 1;
        if (next != null) {
          e.preventDefault();
          jumpToIndex(next);
        }
      }}
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        handlePointer(e);
      }}
      onPointerMove={(e) => {
        if (e.buttons === 1) handlePointer(e);
      }}
      onPointerUp={() => setDragMonth(null)}
      onPointerCancel={() => setDragMonth(null)}
    >
      <div className="pointer-events-none absolute right-0 top-0 h-full w-px bg-slate-200/80" />
      {markers.map((m, i) => {
        const monthNumber = Number(m.month.slice(5, 7));
        const startsYear =
          i === 0 || markers[i - 1].month.slice(0, 4) !== m.month.slice(0, 4);
        const quarter = monthNumber % 3 === 0;
        return (
          <div
            key={`tick-${m.month}-${i}`}
            className={`pointer-events-none absolute right-0 h-px ${
              startsYear
                ? "bg-slate-500/80"
                : quarter
                  ? "bg-slate-400/75"
                  : "bg-slate-300/80"
            }`}
            style={{
              top: Math.min(railH - 1, Math.max(0, railYOf(m))),
              width: startsYear ? 9 : quarter ? 6 : 3,
            }}
          />
        );
      })}
      {placed.map((l) => (
        <div
          key={l.key}
          className={`pointer-events-none absolute right-3 ${
            l.kind === "year"
              ? "text-[11px] font-semibold text-slate-500"
              : "text-[10px] text-slate-400"
          }`}
          style={{ top: Math.min(railH - 14, Math.max(0, l.y)) }}
        >
          {l.text}
        </div>
      ))}
      {!dragMonth && activeMonth && (
        <div
          className="pointer-events-none absolute right-10 z-10 whitespace-nowrap rounded bg-white/90 px-1 text-[10px] font-medium text-slate-600 shadow-sm ring-1 ring-slate-200/80"
          style={{ top: Math.min(railH - 18, Math.max(0, thumbY + 18)) }}
        >
          {Number(activeMonth.slice(5, 7))}월
        </div>
      )}
      <div
        className="pointer-events-none absolute right-0 h-8 w-1 rounded-full bg-slate-500/80 shadow-sm"
        style={{ top: thumbY }}
      />
      {dragMonth && (
        <div
          className="pointer-events-none absolute right-10 rounded-lg bg-slate-800 px-3 py-1.5 text-sm font-medium text-white shadow-lg"
          style={{ top: Math.min(railH - 40, Math.max(0, thumbY - 4)) }}
        >
          {formatMonth(`${dragMonth}-01`)}
        </div>
      )}
    </div>
  );
}

import { useRef, useState } from "react";
import { formatMonth } from "../../lib/dates";

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

  if (totalHeight <= viewportHeight || viewportHeight === 0) return null;

  const railH = viewportHeight;
  const thumbY = (scrollTop / totalHeight) * railH;

  const monthAt = (offset: number): string => {
    let current = markers[0]?.month ?? "";
    for (const m of markers) {
      if (m.offset <= offset) current = m.month;
      else break;
    }
    return current;
  };

  const handlePointer = (e: React.PointerEvent) => {
    const rail = railRef.current;
    if (!rail) return;
    const rect = rail.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    const offset = ratio * (totalHeight - viewportHeight);
    setDragMonth(monthAt(offset));
    onJump(offset);
  };

  // Label rule (Google Photos pattern): a YEAR label is pinned at the start
  // of every year's region (its newest month) and always wins; MONTH labels
  // fill the space between only where they don't collide with anything
  // already placed. Years render bolder than months.
  const GAP = 26; // min px between labels on the rail
  const railYOf = (m: ScrubberMarker) => (m.offset / totalHeight) * railH;
  type RailLabel = { key: string; y: number; text: string; kind: "year" | "month" };
  const placed: RailLabel[] = [];
  let lastYear = "";
  for (const m of markers) {
    const year = m.month.slice(0, 4);
    if (year === lastYear) continue;
    const y = railYOf(m);
    if (!placed.length || y - placed[placed.length - 1].y >= GAP) {
      placed.push({ key: `y-${m.month}`, y, text: year, kind: "year" });
      lastYear = year;
    }
  }
  for (const m of markers) {
    const y = railYOf(m);
    if (placed.every((p) => Math.abs(p.y - y) >= GAP)) {
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
      className="absolute right-0 top-0 z-10 h-full w-10 cursor-row-resize select-none"
      onPointerDown={(e) => {
        (e.target as HTMLElement).setPointerCapture(e.pointerId);
        handlePointer(e);
      }}
      onPointerMove={(e) => {
        if (e.buttons === 1) handlePointer(e);
      }}
      onPointerUp={() => setDragMonth(null)}
    >
      {placed.map((l) => (
        <div
          key={l.key}
          className={`pointer-events-none absolute right-1 ${
            l.kind === "year"
              ? "text-[11px] font-semibold text-slate-500"
              : "text-[10px] text-slate-400"
          }`}
          style={{ top: l.y }}
        >
          {l.text}
        </div>
      ))}
      <div
        className="pointer-events-none absolute right-0 h-8 w-1 rounded-full bg-slate-400/70"
        style={{ top: Math.min(railH - 32, thumbY) }}
      />
      {dragMonth && (
        <div
          className="pointer-events-none absolute right-10 rounded-lg bg-slate-800 px-3 py-1.5 text-sm font-medium text-white shadow-lg"
          style={{ top: Math.min(railH - 40, thumbY) }}
        >
          {formatMonth(`${dragMonth}-01`)}
        </div>
      )}
    </div>
  );
}

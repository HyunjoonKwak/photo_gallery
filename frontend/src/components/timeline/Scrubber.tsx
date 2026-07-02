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

  // Thin out labels so they never overlap (min ~44px apart on the rail).
  const visibleLabels: ScrubberMarker[] = [];
  let lastY = -Infinity;
  for (const m of markers) {
    const y = (m.offset / totalHeight) * railH;
    if (y - lastY >= 44) {
      visibleLabels.push(m);
      lastY = y;
    }
  }

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
      {visibleLabels.map((m) => (
        <div
          key={m.month}
          className="pointer-events-none absolute right-1 text-[10px] text-slate-400"
          style={{ top: (m.offset / totalHeight) * railH }}
        >
          {m.month.endsWith("-01") || m.month === visibleLabels[0]?.month
            ? m.month.slice(0, 4)
            : `${Number(m.month.slice(5, 7))}월`}
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

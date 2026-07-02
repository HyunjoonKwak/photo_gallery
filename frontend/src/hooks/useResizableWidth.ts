import { useCallback, useRef, useState } from "react";

/** Drag-to-resize width for a side panel, persisted in localStorage.
 * Returns the width plus pointer handlers to spread on a drag-handle element.
 */
export function useResizableWidth(
  storageKey: string,
  initial: number,
  min = 160,
  max = 480,
) {
  const clamp = useCallback(
    (w: number) => Math.min(max, Math.max(min, Math.round(w))),
    [min, max],
  );
  const [width, setWidth] = useState<number>(() => {
    try {
      const saved = Number(localStorage.getItem(storageKey));
      return Number.isFinite(saved) && saved > 0 ? clamp(saved) : initial;
    } catch {
      return initial;
    }
  });
  const drag = useRef<{ startX: number; startWidth: number } | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    drag.current = { startX: e.clientX, startWidth: width };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    e.preventDefault();
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag.current) return;
    setWidth(clamp(drag.current.startWidth + (e.clientX - drag.current.startX)));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (!drag.current) return;
    drag.current = null;
    (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    try {
      localStorage.setItem(storageKey, String(width));
    } catch {
      // persistence is best-effort
    }
  };

  return {
    width,
    handleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      role: "separator" as const,
      "aria-orientation": "vertical" as const,
      "aria-label": "패널 크기 조절",
    },
  };
}

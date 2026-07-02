import { useEffect, useState } from "react";
import { useProgressStore } from "../store/progress";

/** Count-based progress bar for bulk operations (IMPROVEMENTS B-6, NN/g):
 * "34/120장 이동 중" + a determinate track. Appears only once the operation
 * has been running ~1s (no flash for quick ops); until the first backend
 * report arrives it shows an indeterminate label.
 */
const SHOW_AFTER_MS = 1000;

export function BulkProgress() {
  const current = useProgressStore((s) => s.current);
  // Tick so the SHOW_AFTER_MS gate opens even without progress patches.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!current) return;
    const t = window.setInterval(() => setTick((v) => v + 1), 300);
    return () => window.clearInterval(t);
  }, [current]);

  if (!current || Date.now() - current.startedAt < SHOW_AFTER_MS) return null;

  const { done, total, label } = current;
  const pct = total > 0 ? Math.round((done / total) * 100) : null;

  return (
    <div
      data-no-boxselect
      role="status"
      className="fixed bottom-20 left-1/2 z-40 w-72 -translate-x-1/2 rounded-xl bg-slate-800/95 px-4 py-3 text-white shadow-lg backdrop-blur"
    >
      <p className="mb-2 text-sm font-medium">
        {total > 0 ? `${done}/${total}장 ${label} 중…` : `${label} 중…`}
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-600">
        {pct != null ? (
          <div
            className="h-full rounded-full bg-blue-400 transition-[width] duration-500"
            style={{ width: `${pct}%` }}
          />
        ) : (
          <div className="h-full w-1/3 animate-pulse rounded-full bg-blue-400" />
        )}
      </div>
    </div>
  );
}

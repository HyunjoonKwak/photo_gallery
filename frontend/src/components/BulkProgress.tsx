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

  const { done, total, label, unit } = current;
  const pct = total > 0 ? Math.round((done / total) * 100) : null;
  // 완료 프레임: 마지막 항목까지 처리되면 잠깐 "✓ … 완료"를 보여준 뒤(스토어가
  // 곧 clear) 사라진다 — 작업이 끝났는지 명확히 알 수 있게.
  const complete = total > 0 && done >= total;

  return (
    <div
      data-no-boxselect
      role="status"
      className="fixed bottom-32 left-1/2 z-40 w-72 -translate-x-1/2 rounded-xl bg-slate-800/95 px-4 py-3 text-white shadow-lg backdrop-blur md:bottom-20"
    >
      <p className="mb-2 text-sm font-medium">
        {complete
          ? unit === "%"
            ? `✓ ${label} 완료`
            : `✓ ${total}${unit} ${label} 완료`
          : total > 0
            ? unit === "%"
              ? `${done}% ${label} 중…`
              : `${done}/${total}${unit} ${label} 중…`
            : `${label} 중…`}
      </p>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-600">
        {complete ? (
          <div className="h-full w-full rounded-full bg-emerald-400" />
        ) : pct != null ? (
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

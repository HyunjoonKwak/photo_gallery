import { useEffect, useRef } from "react";
import { useToastStore, type Toast } from "../store/toast";

const TOAST_MS = 8000; // 7–10s for action-carrying toasts (IMPROVEMENTS B-6)

function ToastItem({ toast }: { toast: Toast }) {
  const dismiss = useToastStore((s) => s.dismiss);
  const timerRef = useRef<number | undefined>(undefined);

  const startTimer = () => {
    timerRef.current = window.setTimeout(() => dismiss(toast.id), TOAST_MS);
  };

  useEffect(() => {
    startTimer();
    return () => window.clearTimeout(timerRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div
      // Hovering pauses the dismiss timer so the user can read/act.
      onMouseEnter={() => window.clearTimeout(timerRef.current)}
      onMouseLeave={startTimer}
      className="pointer-events-auto flex items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-sm text-white shadow-lg"
    >
      <span>{toast.message}</span>
      {toast.action && (
        <button
          onClick={() => {
            toast.action?.run();
            dismiss(toast.id);
          }}
          className="shrink-0 rounded-lg px-2 py-1 font-semibold text-blue-300 hover:bg-slate-700 hover:text-blue-200"
        >
          {toast.action.label}
        </button>
      )}
      <button
        onClick={() => dismiss(toast.id)}
        className="shrink-0 rounded p-0.5 text-slate-400 hover:text-white"
        aria-label="닫기"
      >
        ✕
      </button>
    </div>
  );
}

export function Toasts() {
  const toasts = useToastStore((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div
      data-no-boxselect
      className="pointer-events-none fixed bottom-20 left-1/2 z-50 flex -translate-x-1/2 flex-col gap-2"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFileOps } from "../hooks/useFileOps";
import type { OperationEntry } from "../api/types";

const TYPE_ICON: Record<OperationEntry["type"], string> = {
  move: "📦",
  copy: "📄",
  delete: "🗑",
  mkdir: "📁",
};

function timeLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Right slide-over listing recent operations with per-entry undo (spec 9.1).
 * This is the safety net after the undo toast disappears (IMPROVEMENTS B-6).
 */
export function OperationsPanel({ onClose }: { onClose: () => void }) {
  const ops = useFileOps();
  const query = useQuery({ queryKey: ["ops"], queryFn: api.listOps });
  const entries = query.data?.operations ?? [];

  return (
    <div
      data-no-boxselect
      className="fixed inset-y-0 right-0 z-40 flex w-80 flex-col border-l border-slate-200 bg-white shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <h3 className="text-sm font-bold text-slate-800">작업 기록</h3>
        <button
          onClick={onClose}
          aria-label="닫기"
          className="rounded p-1 text-slate-400 hover:text-slate-600"
        >
          ✕
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
        {query.isPending && (
          <p className="px-1 py-4 text-sm text-slate-400">불러오는 중…</p>
        )}
        {entries.length === 0 && !query.isPending && (
          <p className="px-1 py-4 text-sm text-slate-400">
            아직 작업 기록이 없습니다.
          </p>
        )}
        <ul className="space-y-1">
          {entries.map((op) => (
            <li
              key={op.id}
              className={`rounded-xl border px-3 py-2 ${
                op.status === "undone"
                  ? "border-slate-100 bg-slate-50 opacity-60"
                  : "border-slate-200"
              }`}
            >
              <div className="flex items-start gap-2">
                <span aria-hidden className="mt-0.5">
                  {TYPE_ICON[op.type] ?? "•"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-slate-700">
                    {op.summary}
                    {op.status === "undone" && (
                      <span className="ml-1 text-xs text-slate-400">(되돌림)</span>
                    )}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    {timeLabel(op.created_at)}
                    {op.target_user && ` · 대상: ${op.target_user} (관리자 수행)`}
                  </p>
                </div>
                {op.can_undo && (
                  <button
                    onClick={() => ops.undo(op.id)}
                    className="shrink-0 rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
                  >
                    되돌리기
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

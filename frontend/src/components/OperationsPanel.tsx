import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuthStore } from "../store/auth";
import { useToastStore } from "../store/toast";
import { useFileOps } from "../hooks/useFileOps";
import type { OperationEntry } from "../api/types";

const TYPE_ICON: Record<OperationEntry["type"], string> = {
  move: "📦",
  copy: "📄",
  delete: "🗑",
  mkdir: "📁",
  empty_trash: "🧹",
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

/** Confirmation dialog for the ONLY irreversible operation (IMPROVEMENTS
 * B-6: 영구 삭제만 확인 + 파괴적 버튼은 색·간격으로 분리). */
function EmptyTrashConfirm({
  items,
  busy,
  onCancel,
  onConfirm,
}: {
  items: number;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-80 rounded-2xl bg-white p-5 shadow-xl">
        <h4 className="text-sm font-bold text-slate-800">휴지통 비우기</h4>
        <p className="mt-2 text-sm leading-relaxed text-slate-600">
          휴지통의 사진 <b className="text-red-600">{items.toLocaleString()}장을
          영구 삭제</b>합니다. 삭제된 작업들의 되돌리기도 함께 사라지며,{" "}
          <b>이 작업은 되돌릴 수 없습니다.</b>
        </p>
        <div className="mt-5 flex items-center justify-between">
          <button
            onClick={onCancel}
            className="rounded-lg border border-slate-300 px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            취소
          </button>
          {/* destructive: red + separated from the neutral button */}
          <button
            onClick={onConfirm}
            disabled={busy}
            className="rounded-lg bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            {busy ? "비우는 중…" : `${items.toLocaleString()}장 영구 삭제`}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Right slide-over listing recent operations with per-entry undo (spec 9.1).
 * This is the safety net after the undo toast disappears (IMPROVEMENTS B-6).
 * Also hosts 휴지통 비우기 (admin-only — it kills everyone's delete undos).
 */
export function OperationsPanel({ onClose }: { onClose: () => void }) {
  const ops = useFileOps();
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const query = useQuery({ queryKey: ["ops"], queryFn: api.listOps });
  const entries = query.data?.operations ?? [];

  const trashQuery = useQuery({ queryKey: ["trash"], queryFn: api.trashStats });
  const trash = trashQuery.data;

  const emptyMutation = useMutation({
    mutationFn: api.emptyTrash,
    onSuccess: (res) => {
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      queryClient.invalidateQueries({ queryKey: ["trash"] });
      useToastStore.getState().push(`${res.summary} 완료`);
    },
    onError: (err) => {
      setConfirming(false);
      useToastStore.getState().push((err as Error).message);
    },
  });

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

      {/* App trash summary + admin-only empty action */}
      {trash && trash.items > 0 && (
        <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-2.5">
          <p className="text-xs text-slate-500">
            🗑 휴지통: <b>{trash.items.toLocaleString()}장</b> ({trash.operations}개
            작업)
          </p>
          {user?.role === "admin" && (
            <button
              onClick={() => setConfirming(true)}
              className="rounded-lg border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
            >
              비우기
            </button>
          )}
        </div>
      )}

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
                op.status === "undone" || op.status === "purged"
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
                    {op.status === "purged" && (
                      <span className="ml-1 text-xs text-red-400">
                        (영구 삭제됨)
                      </span>
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

      {confirming && trash && (
        <EmptyTrashConfirm
          items={trash.items}
          busy={emptyMutation.isPending}
          onCancel={() => setConfirming(false)}
          onConfirm={() => emptyMutation.mutate()}
        />
      )}
    </div>
  );
}

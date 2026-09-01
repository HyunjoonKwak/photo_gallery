import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useAuthStore } from "../store/auth";
import { useToastStore } from "../store/toast";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import type { OperationEntry } from "../api/types";

const TYPE_ICON: Record<OperationEntry["type"], string> = {
  move: "📦",
  copy: "📄",
  delete: "🗑",
  mkdir: "📁",
  rmdir: "📁",
  trash_folder: "🗑",
  move_folder: "📁",
  copy_folder: "📁",
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
export function OperationsPanel({
  onClose,
  initialTrashOpen = false,
}: {
  onClose: () => void;
  /** true면 휴지통 브라우저가 펼쳐진 채 열린다 — 더보기의 "휴지통" 진입용. */
  initialTrashOpen?: boolean;
}) {
  const ops = useFileOps();
  const user = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [trashOpen, setTrashOpen] = useState(initialTrashOpen);

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
            <button
              onClick={() => setTrashOpen((v) => !v)}
              className="ml-2 rounded border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-100"
            >
              {trashOpen ? "닫기" : "내용 보기"}
            </button>
          </p>
          {user?.role === "admin" && (
            <button
              onClick={() => {
                // B-7: 타인 라이브러리 열람 중 영구 삭제 금지 — 되돌리기가
                // 전 가족의 undo를 무효화하는 유일한 비가역 작업이라, 본인
                // 컨텍스트로 돌아와 실행하게 한다.
                if (useTimelineStore.getState().viewedOwner) {
                  useToastStore
                    .getState()
                    .push("타인 사진 열람 중에는 비울 수 없습니다. 내 사진으로 돌아가 실행하세요.");
                  return;
                }
                setConfirming(true);
              }}
              className="rounded-lg border border-red-200 px-2 py-1 text-xs text-red-600 hover:bg-red-50"
            >
              비우기
            </button>
          )}
        </div>
      )}
      {trashOpen && <TrashBrowser onDone={() => setTrashOpen(false)} />}

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto px-3 py-2">
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


/** 휴지통 내용(사진 단위) + 선택 복원 — 작업 undo의 부분집합. */
function TrashBrowser({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["trash-items"], queryFn: api.trashItems });
  const [sel, setSel] = useState<Set<string>>(new Set());
  const keyOf = (e: { op_id: number; item_id: string }) => `${e.op_id}:${e.item_id}`;
  const restoreMut = useMutation({
    mutationFn: (entries: { op_id: number; item_id: string }[]) =>
      api.trashRestore(entries),
    onSuccess: (res) => {
      useToastStore.getState().push(`${res.summary}했습니다`);
      setSel(new Set());
      queryClient.invalidateQueries({ queryKey: ["trash-items"] });
      queryClient.invalidateQueries({ queryKey: ["trash"] });
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      queryClient.invalidateQueries({ queryKey: ["buckets"] });
      queryClient.invalidateQueries({ queryKey: ["folder-items"] });
    },
    onError: (err) => useToastStore.getState().push((err as Error).message),
  });
  const items = q.data?.items ?? [];
  const toggle = (k: string) =>
    setSel((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  return (
    <div className="scroll-thin max-h-64 overflow-y-auto border-b border-slate-100">
      {q.isPending && (
        <p className="px-4 py-3 text-xs text-slate-400">불러오는 중…</p>
      )}
      {!q.isPending && items.length === 0 && (
        <p className="px-4 py-3 text-xs text-slate-400">
          개별 복원 가능한 사진이 없습니다. (폴더째 삭제는 작업 목록에서 통째로
          되돌리세요.)
        </p>
      )}
      {items.map((e) => {
        const k = keyOf(e);
        return (
          <label
            key={k}
            className="flex cursor-pointer items-center gap-2 px-4 py-1.5 text-xs hover:bg-slate-50"
          >
            <input
              type="checkbox"
              checked={sel.has(k)}
              onChange={() => toggle(k)}
            />
            <span className="min-w-0 flex-1 truncate text-slate-700">
              {e.filename}
            </span>
            <span className="hidden max-w-[40%] truncate text-slate-400 sm:inline">
              {e.src_dir}
            </span>
            <span className="shrink-0 text-slate-400">{e.day}</span>
          </label>
        );
      })}
      {items.length > 0 && (
        <div className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-100 bg-white px-4 py-2">
          <button
            onClick={() => {
              const entries = items
                .filter((e) => sel.has(keyOf(e)))
                .map((e) => ({ op_id: e.op_id, item_id: e.item_id }));
              if (entries.length) restoreMut.mutate(entries);
            }}
            disabled={sel.size === 0 || restoreMut.isPending}
            className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-40"
          >
            {restoreMut.isPending ? "복원 중…" : `${sel.size}장 원위치 복원`}
          </button>
          <button
            onClick={onDone}
            className="rounded-lg px-3 py-1 text-xs text-slate-500 hover:bg-slate-100"
          >
            닫기
          </button>
        </div>
      )}
    </div>
  );
}

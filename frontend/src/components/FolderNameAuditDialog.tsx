import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AreaScope } from "../api/client";
import { useToastStore } from "../store/toast";
import { useDialogFocus } from "../hooks/useDialogFocus";

/** 폴더 이름 정리 — root(현재 폴더) 하위를 재귀 스캔해 이름 규칙(날짜부 밑줄→
 * 하이픈)에 어긋난 폴더를 찾아 `현재 → 교정안` 목록으로 보여주고, 체크한 것만
 * 이름 변경한다. 이름 변경은 되돌리기(undo)가 없으므로 검토 후 선택 적용이 안전.
 */
export function FolderNameAuditDialog({
  rootId,
  area,
  onClose,
  onDone,
}: {
  rootId: string | null;
  area?: AreaScope;
  onClose: () => void;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const dialogRef = useDialogFocus<HTMLDivElement>(onClose);
  const pushToast = useToastStore((s) => s.push);
  const q = useQuery({
    queryKey: ["folder-name-audit", rootId, area?.zone ?? "", area?.targetUser ?? ""],
    queryFn: () => api.folderNameAudit(rootId, area),
  });
  const items = q.data?.items ?? [];

  // 기본 전체 선택. 적용 대상 id 집합.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [applying, setApplying] = useState(false);
  const [done, setDone] = useState<number | null>(null);
  const selected = items.filter((i) => !excluded.has(i.id));

  const toggle = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const apply = async () => {
    if (selected.length === 0) return;
    setApplying(true);
    let ok = 0;
    // 순차 실행 — 실 NAS FileStation 태스크가 겹치지 않게.
    for (const it of selected) {
      try {
        await api.renameFolder(it.id, it.proposed_name, "personal", area);
        ok += 1;
      } catch {
        break;
      }
    }
    setApplying(false);
    setDone(ok);
    qc.invalidateQueries({ queryKey: ["folders"] });
    qc.invalidateQueries({ queryKey: ["folder-counts"] });
    qc.invalidateQueries({ queryKey: ["folder-items"] });
    pushToast(
      ok === selected.length
        ? `${ok}개 폴더 이름을 정리했습니다.`
        : `${ok}/${selected.length}개 정리 후 중단됐습니다.`,
    );
    onDone();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        data-modal-root="true"
        role="dialog"
        aria-modal="true"
        aria-label="폴더 이름 정리"
        tabIndex={-1}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800">폴더 이름 정리</h3>
          <button
            data-autofocus="true"
            aria-label="닫기"
            onClick={onClose}
            className="rounded-full px-2 py-0.5 text-slate-400 hover:bg-slate-100"
          >
            ✕
          </button>
        </div>

        <div className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
          현재 폴더 아래에서 <b>날짜부가 밑줄</b>(예 2016_06_06)인 폴더를 찾아
          하이픈으로 바꿉니다. 체크한 것만 적용됩니다. (사진·썸네일은 그대로)
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {q.isPending ? (
            <p className="p-6 text-center text-sm text-slate-400">스캔 중…</p>
          ) : q.isError ? (
            <p className="p-6 text-center text-sm text-slate-400">
              스캔에 실패했습니다. (기기 백업 폴더 뷰에서 사용하세요)
            </p>
          ) : done !== null ? (
            <p className="p-6 text-center text-sm text-slate-600">
              {done}개 폴더 이름을 정리했습니다. 남은 항목은 닫고 다시 스캔해
              확인하세요.
            </p>
          ) : items.length === 0 ? (
            <p className="p-6 text-center text-sm text-slate-400">
              교정할 폴더가 없습니다. 👍
            </p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {items.map((it) => {
                const on = !excluded.has(it.id);
                return (
                  <li key={it.id}>
                    <button
                      onClick={() => toggle(it.id)}
                      className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-slate-50"
                    >
                      <span
                        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded text-[10px] font-bold ${
                          on ? "bg-blue-600 text-white" : "bg-slate-200 text-slate-400"
                        }`}
                      >
                        {on ? "✓" : ""}
                      </span>
                      <span className="min-w-0 flex-1 text-xs">
                        <span className="block truncate text-slate-400 line-through">
                          {it.current_name}
                        </span>
                        <span className="block truncate font-medium text-slate-800">
                          {it.proposed_name}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {done === null && items.length > 0 && (
          <div className="flex items-center justify-between gap-2 border-t border-slate-100 px-4 py-3">
            <span className="text-xs text-slate-500">
              {selected.length}/{items.length}개 선택
            </span>
            <button
              onClick={apply}
              disabled={applying || selected.length === 0}
              className="rounded-lg bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-40"
            >
              {applying ? "적용 중…" : `${selected.length}개 이름 변경`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

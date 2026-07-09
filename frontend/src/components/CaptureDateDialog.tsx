import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useProgressStore } from "../store/progress";
import { useToastStore } from "../store/toast";

/** 촬영일 교정 — root(홈 폴더 경로) 하위를 스캔해 파일 날짜(mtime, 복사시각으로
 * 오염됨)를 파일명에서 읽은 실제 촬영일로 파일에 기록(JPEG=EXIF, 전 포맷=mtime).
 * 자동 감지분은 한 번에 적용, 날짜를 못 읽은 사진은 사용자가 직접 지정한다.
 * 파일을 실제로 수정하므로 되돌리기가 없다(자동은 EXIF 있는 파일을 건드리지 않음). */
function genKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID();
  return `cap-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "-";
  return iso.slice(0, 10);
}

export function CaptureDateDialog({
  root,
  onClose,
  onDone,
}: {
  root: string;
  onClose: () => void;
  onDone: () => void;
}) {
  const qc = useQueryClient();
  const pushToast = useToastStore((s) => s.push);
  const q = useQuery({
    queryKey: ["capture-audit", root],
    queryFn: () => api.captureAudit(root),
  });
  const items = q.data?.items ?? [];
  const autoItems = useMemo(
    () => items.filter((i) => i.source === "filename"),
    [items],
  );
  const manualItems = useMemo(
    () => items.filter((i) => i.source === "none"),
    [items],
  );

  const [busy, setBusy] = useState(false);
  const [manualDates, setManualDates] = useState<Record<string, string>>({});

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["folder-items"] });
    qc.invalidateQueries({ queryKey: ["folders"] });
    qc.invalidateQueries({ queryKey: ["buckets"] });
    qc.invalidateQueries({ queryKey: ["capture-audit", root] });
  };

  const applyAuto = async () => {
    if (autoItems.length === 0 || busy) return;
    setBusy(true);
    const key = genKey();
    useProgressStore.getState().start(key, "촬영일 교정", "장");
    useProgressStore.getState().patch(key, 0, autoItems.length);
    const timer = window.setInterval(async () => {
      try {
        const r = await api.opProgress(key);
        if (r.active) useProgressStore.getState().patch(key, r.done, r.total);
      } catch {
        // best-effort
      }
    }, 700);
    try {
      const res = await api.captureFix(
        autoItems.map((i) => i.path),
        key,
      );
      pushToast(
        `${res.ok}개 촬영일을 교정했습니다` +
          (res.skipped ? ` (건너뜀 ${res.skipped})` : "") +
          (res.failed ? ` (실패 ${res.failed})` : ""),
      );
      invalidate();
      onDone();
    } catch (e) {
      pushToast((e as Error).message);
    } finally {
      window.clearInterval(timer);
      useProgressStore.getState().clear(key);
      setBusy(false);
    }
  };

  const applyManual = async () => {
    const picked = manualItems
      .map((i) => ({ path: i.path, date: manualDates[i.path] }))
      .filter((x): x is { path: string; date: string } => Boolean(x.date));
    if (picked.length === 0 || busy) return;
    setBusy(true);
    try {
      const res = await api.captureFixManual(picked);
      pushToast(
        `${res.ok}개 촬영일을 지정했습니다` +
          (res.failed ? ` (실패 ${res.failed})` : ""),
      );
      invalidate();
      onDone();
    } catch (e) {
      pushToast((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const pickedManual = manualItems.filter((i) => manualDates[i.path]).length;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800">촬영일 교정</h3>
          <button
            onClick={onClose}
            className="rounded-full px-2 py-0.5 text-slate-400 hover:bg-slate-100"
          >
            ✕
          </button>
        </div>

        <div className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
          현재 폴더 아래 사진의 촬영일이 <b>복사시각</b>으로 잘못 잡힌 것을, 파일명에
          담긴 실제 촬영일로 <b>파일에 기록</b>합니다(이동해도 유지). 되돌리기는
          없습니다.
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          {q.isPending ? (
            <p className="p-6 text-center text-sm text-slate-400">스캔 중…</p>
          ) : q.isError ? (
            <p className="p-6 text-center text-sm text-slate-400">
              스캔에 실패했습니다. (본인 홈 폴더에서 사용하세요)
            </p>
          ) : items.length === 0 ? (
            <p className="p-6 text-center text-sm text-slate-400">
              사진이 없습니다.
            </p>
          ) : (
            <div className="flex flex-col gap-4">
              {/* 자동 교정 가능 */}
              <section>
                <div className="mb-1 flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-700">
                    자동 교정 가능 ({autoItems.length})
                  </h4>
                  <button
                    onClick={applyAuto}
                    disabled={busy || autoItems.length === 0}
                    className="rounded-lg bg-slate-800 px-3 py-1 text-xs font-medium text-white hover:bg-slate-700 disabled:opacity-40"
                  >
                    {autoItems.length}개 자동 교정
                  </button>
                </div>
                {autoItems.length === 0 ? (
                  <p className="py-2 text-xs text-slate-400">없음</p>
                ) : (
                  <ul className="max-h-40 overflow-y-auto rounded-lg border border-slate-100">
                    {autoItems.slice(0, 200).map((it) => (
                      <li
                        key={it.path}
                        className="flex items-center justify-between gap-2 px-2 py-1 text-xs odd:bg-slate-50"
                      >
                        <span className="min-w-0 flex-1 truncate text-slate-600">
                          {it.filename}
                        </span>
                        <span className="shrink-0 text-slate-400 line-through">
                          {fmtDate(it.current)}
                        </span>
                        <span className="shrink-0 font-medium text-emerald-600">
                          → {fmtDate(it.detected)}
                        </span>
                      </li>
                    ))}
                    {autoItems.length > 200 && (
                      <li className="px-2 py-1 text-center text-[11px] text-slate-400">
                        …외 {autoItems.length - 200}개 (모두 교정됨)
                      </li>
                    )}
                  </ul>
                )}
              </section>

              {/* 정보 없음 — 수동 지정 */}
              <section>
                <div className="mb-1 flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-700">
                    정보 없음 · 수동 지정 ({manualItems.length})
                  </h4>
                  {manualItems.length > 0 && (
                    <button
                      onClick={applyManual}
                      disabled={busy || pickedManual === 0}
                      className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40"
                    >
                      {pickedManual}개 날짜 적용
                    </button>
                  )}
                </div>
                {manualItems.length === 0 ? (
                  <p className="py-2 text-xs text-slate-400">
                    모두 날짜를 인식했습니다 👍
                  </p>
                ) : (
                  <ul className="max-h-52 overflow-y-auto rounded-lg border border-slate-100">
                    {manualItems.slice(0, 300).map((it) => (
                      <li
                        key={it.path}
                        className="flex items-center justify-between gap-2 px-2 py-1 text-xs odd:bg-slate-50"
                      >
                        <span className="min-w-0 flex-1 truncate text-slate-600">
                          {it.filename}
                        </span>
                        <input
                          type="date"
                          value={manualDates[it.path] ?? ""}
                          onChange={(e) =>
                            setManualDates((prev) => ({
                              ...prev,
                              [it.path]: e.target.value,
                            }))
                          }
                          className="shrink-0 rounded border border-slate-200 px-1 py-0.5 text-xs text-slate-700"
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

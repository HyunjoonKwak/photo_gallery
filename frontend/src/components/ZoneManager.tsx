import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ZoneBrowseEntry } from "../api/types";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { QueryErrorState } from "./QueryErrorState";
import { useGalleryCapabilities } from "../hooks/useGalleryCapabilities";

/** 1차 구역(기기 백업) 관리 모달: 등록된 구역 목록/삭제 + 새 구역 추가.
 * 추가는 내 홈(/homes/<나>) 아래를 FileStation으로 탐색해 폴더를 고른다
 * (Synology Photos 인덱스 밖이라 일반 폴더 API로는 안 보임). */
export function ZoneManager({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const dialogRef = useDialogFocus<HTMLDivElement>(onClose);
  const { capabilities } = useGalleryCapabilities();
  const zonesQuery = useQuery({ queryKey: ["zones"], queryFn: api.listZones });
  const zones = zonesQuery.data?.zones ?? [];

  // 폴더 탐색 상태 (추가 폼)
  const [browsePath, setBrowsePath] = useState<string | undefined>(undefined);
  const browseQuery = useQuery({
    queryKey: ["zone-browse", browsePath ?? "root"],
    queryFn: () => api.browseZonePath(browsePath),
  });
  const [picked, setPicked] = useState<{ path: string; name: string } | null>(null);
  const [label, setLabel] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const invalidateZones = () =>
    queryClient.invalidateQueries({ queryKey: ["zones"] });

  const createMut = useMutation({
    mutationFn: api.createZone,
    onSuccess: () => {
      invalidateZones();
      setPicked(null);
      setLabel("");
      setErr(null);
    },
    onError: (e) => setErr((e as Error).message),
  });
  const deleteMut = useMutation({
    mutationFn: api.deleteZone,
    onSuccess: invalidateZones,
  });

  const pickFolder = (d: ZoneBrowseEntry) => {
    setPicked({ path: d.path, name: d.name });
    if (!label) setLabel(d.name);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        data-modal-root="true"
        role="dialog"
        aria-modal="true"
        aria-label="기기 백업 관리"
        tabIndex={-1}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-800">기기 백업 관리</h3>
          <button
            data-autofocus="true"
            aria-label="닫기"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100"
          >
            ✕
          </button>
        </div>
        <p className="mb-3 text-xs leading-relaxed text-slate-500">
          Synology Photos 밖(타임라인에 안 나오는) 폴더를 기기 백업으로 등록하면,
          여기서 사진을 골라 내 사진(타임라인)으로 옮길 수 있습니다.
        </p>

        {/* 등록된 구역 */}
        <div className="mb-4">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            등록된 구역 ({zones.length})
          </h4>
          {zonesQuery.isPending ? (
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
              불러오는 중…
            </p>
          ) : zonesQuery.isError && zones.length === 0 ? (
            <QueryErrorState
              compact
              message="기기 백업 목록을 불러오지 못했습니다."
              onRetry={() => void zonesQuery.refetch()}
            />
          ) : zones.length === 0 ? (
            <p className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
              아직 없습니다. 아래에서 폴더를 골라 추가하세요.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-100">
              {zones.map((z) => (
                <li
                  key={z.id}
                  className="flex items-center gap-2 px-3 py-2 text-sm"
                >
                  <span aria-hidden>📦</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium text-slate-700">
                      {z.label}
                    </span>
                    <span className="block truncate text-[11px] text-slate-400">
                      {z.root_path}
                    </span>
                  </span>
                  {capabilities.physical_mutations && (
                    <button
                      onClick={() => deleteMut.mutate(z.id)}
                      className="shrink-0 rounded-lg border border-red-200 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                    >
                      삭제
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* 새 구역 추가 — 폴더 탐색 */}
        {capabilities.physical_mutations ? (
        <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
          <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
            새 구역 추가 — 폴더 선택
          </h4>
          <div className="rounded-lg border border-slate-100">
            <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-1.5 text-xs text-slate-500">
              <button
                disabled={!browseQuery.data?.parent}
                onClick={() => setBrowsePath(browseQuery.data?.parent ?? undefined)}
                className="rounded px-1.5 py-0.5 hover:bg-slate-100 disabled:opacity-30"
              >
                ↑ 상위
              </button>
              <span className="min-w-0 flex-1 truncate font-mono">
                {browseQuery.data?.path ?? "…"}
              </span>
            </div>
            {browseQuery.isPending ? (
              <p className="px-3 py-3 text-xs text-slate-400">불러오는 중…</p>
            ) : browseQuery.isError ? (
              <QueryErrorState
                compact
                message="폴더 목록을 불러오지 못했습니다."
                onRetry={() => void browseQuery.refetch()}
              />
            ) : (browseQuery.data?.dirs.length ?? 0) === 0 ? (
              <p className="px-3 py-3 text-xs text-slate-400">하위 폴더가 없습니다.</p>
            ) : (
              <ul className="scroll-thin max-h-40 overflow-y-auto">
                {browseQuery.data?.dirs.map((d) => (
                  <li key={d.path} className="flex items-center">
                    <button
                      onClick={() => pickFolder(d)}
                      className={`flex min-w-0 flex-1 items-center gap-2 px-3 py-1.5 text-left text-sm ${
                        picked?.path === d.path
                          ? "bg-indigo-50 font-medium text-indigo-700"
                          : "text-slate-600 hover:bg-slate-50"
                      }`}
                    >
                      <span aria-hidden>📁</span>
                      <span className="min-w-0 flex-1 truncate">{d.name}</span>
                    </button>
                    <button
                      onClick={() => setBrowsePath(d.path)}
                      title="열기"
                      className="shrink-0 px-2 py-1.5 text-slate-300 hover:text-slate-500"
                    >
                      ›
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {picked && (
            <div className="mt-3 rounded-lg bg-indigo-50/60 p-3">
              <p className="mb-1 text-xs text-slate-500">
                선택: <span className="font-mono">{picked.path}</span>
              </p>
              <div className="flex items-center gap-2">
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  placeholder="구역 이름 (예: 기기 백업)"
                  className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-1 text-sm outline-none focus:border-indigo-400"
                />
                <button
                  disabled={!label.trim() || createMut.isPending}
                  onClick={() =>
                    createMut.mutate({ root_path: picked.path, label: label.trim() })
                  }
                  className="shrink-0 rounded-lg bg-indigo-600 px-3 py-1 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
                >
                  추가
                </button>
              </div>
              {err && <p className="mt-1 text-xs text-red-500">{err}</p>}
            </div>
          )}
        </div>
        ) : (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
            원본 보호 모드에서는 기존 기기 백업 구역을 조회할 수만 있습니다.
          </p>
        )}
      </div>
    </div>
  );
}

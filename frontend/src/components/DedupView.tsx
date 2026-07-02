import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, thumbnailUrl } from "../api/client";
import type { DedupGroup, DedupItem } from "../api/types";
import { formatBytes } from "../lib/dates";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";

/** Duplicate cleanup view (D절):
 * scan → the groups list *is* the dry-run (what gets deleted + saved bytes) →
 * per-group KEEP SET (multi-select): the suggested reference starts kept, and
 * each photo's badge toggles 보관↔삭제 — burst/similar groups can keep
 * several shots. Cleanup reuses the standard delete flow (trash + undo).
 * The threshold slider re-groups near-duplicates live from persisted hashes.
 */
export function DedupView() {
  const space = useTimelineStore((s) => s.space);
  const queryClient = useQueryClient();
  const ops = useFileOps();
  const [threshold, setThreshold] = useState(5);
  // Per-group keep set (default: the suggested reference only).
  const [keepOverride, setKeepOverride] = useState<Map<string, Set<string>>>(
    new Map(),
  );

  const statusQuery = useQuery({
    queryKey: ["dedup-status", space],
    queryFn: () => api.dedupStatus(space),
    refetchInterval: (q) =>
      q.state.data?.job?.status === "running" ? 700 : false,
  });
  const job = statusQuery.data?.job ?? null;
  const running = job?.status === "running";

  const groupsQuery = useQuery({
    queryKey: ["dedup-groups", space, threshold],
    queryFn: () => api.dedupGroups(space, threshold),
    enabled: !running,
  });
  const data = groupsQuery.data;

  const scanMutation = useMutation({
    mutationFn: () => api.dedupScan(space),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dedup-status", space] });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () => api.dedupCancel(space),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["dedup-status", space] }),
  });

  // Re-fetch groups when a scan finishes.
  const jobDoneAt = job?.status === "done" ? job.updated_at : null;
  useMemo(() => {
    if (jobDoneAt) queryClient.invalidateQueries({ queryKey: ["dedup-groups"] });
  }, [jobDoneAt, queryClient]);

  // Effective keep set: user's toggles ∩ current items; never empty — falls
  // back to the suggested reference (stale overrides can't nuke a group).
  const keepSetOf = (g: DedupGroup): Set<string> => {
    const override = keepOverride.get(g.id);
    const valid = new Set(
      [...(override ?? [g.reference_id])].filter((id) =>
        g.items.some((i) => i.id === id),
      ),
    );
    if (valid.size === 0) valid.add(g.reference_id);
    return valid;
  };

  const toggleKeep = (g: DedupGroup, id: string) => {
    const next = new Set(keepSetOf(g));
    if (next.has(id)) {
      if (next.size === 1) return; // always keep at least one photo
      next.delete(id);
    } else {
      next.add(id);
    }
    setKeepOverride((prev) => new Map(prev).set(g.id, next));
  };

  const cleanupGroup = (g: DedupGroup) => {
    const keep = keepSetOf(g);
    const victims = g.items.filter((i) => !keep.has(i.id)).map((i) => i.id);
    if (victims.length) ops.remove(victims);
  };

  const cleanupAll = () => {
    if (!data) return;
    const victims = data.groups.flatMap((g) => {
      const keep = keepSetOf(g);
      return g.items.filter((i) => !keep.has(i.id)).map((i) => i.id);
    });
    if (victims.length) ops.remove(victims);
  };

  const progressPct =
    job && job.total > 0 ? Math.round((job.processed / job.total) * 100) : 0;

  return (
    <div className="h-full overflow-y-auto" data-no-boxselect>
      <div className="mx-auto max-w-4xl px-4 py-4">
        {/* Control bar */}
        <div className="flex flex-wrap items-center gap-4 rounded-2xl bg-white p-4 shadow-sm">
          <div>
            <h2 className="text-sm font-bold text-slate-800">중복 사진 정리</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {space === "team" ? "공용" : "개인"} 공간 · 썸네일 기반
              SHA-256(정확) + pHash(유사)
            </p>
          </div>

          {running ? (
            <div className="flex flex-1 items-center gap-3">
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
                <div
                  className="h-full bg-blue-500 transition-all"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <span className="whitespace-nowrap text-xs text-slate-500">
                {job?.processed}/{job?.total}장 스캔 중…
              </span>
              <button
                onClick={() => cancelMutation.mutate()}
                className="rounded-lg border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
              >
                취소
              </button>
            </div>
          ) : (
            <button
              onClick={() => scanMutation.mutate()}
              disabled={scanMutation.isPending}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {data?.scanned ? "재스캔" : "스캔 시작"}
            </button>
          )}

          <label className="ml-auto flex items-center gap-2 text-xs text-slate-600">
            유사 기준 (Hamming ≤ {threshold})
            <input
              type="range"
              min={0}
              max={7}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-32"
            />
          </label>
        </div>

        {job?.status === "failed" && (
          <p className="mt-3 rounded-xl bg-red-50 px-4 py-2 text-sm text-red-600">
            스캔 실패: {job.error}
          </p>
        )}

        {/* Summary + bulk action — the list below is the dry-run preview */}
        {data?.scanned && data.groups.length > 0 && (
          <div className="mt-4 flex items-center justify-between rounded-2xl bg-slate-800 px-4 py-3 text-sm text-white">
            <span>
              중복 그룹 <b>{data.total_groups}개</b>
              {data.total_groups > data.groups.length &&
                ` (절약량 상위 ${data.groups.length}개 표시)`}{" "}
              · 전체 정리 시 <b>{formatBytes(data.total_wasted_bytes)}</b> 절약
              (그룹마다 보관본 1장은 유지)
            </span>
            <button
              onClick={cleanupAll}
              disabled={ops.isBusy}
              className="rounded-lg bg-red-500 px-3 py-1.5 text-xs font-semibold hover:bg-red-600 disabled:opacity-50"
            >
              표시된 {data.groups.length}개 그룹 정리 (휴지통 + 되돌리기)
            </button>
          </div>
        )}

        {data?.scanned && data.groups.length === 0 && !running && (
          <p className="mt-8 text-center text-sm text-slate-400">
            중복 사진이 없습니다. 🎉
          </p>
        )}
        {!data?.scanned && !running && (
          <p className="mt-8 text-center text-sm text-slate-400">
            아직 스캔하지 않았습니다. [스캔 시작]을 눌러 중복을 찾아보세요.
          </p>
        )}

        {/* Group cards */}
        <div className="mt-4 space-y-4 pb-16">
          {data?.groups.map((g) => (
            <GroupCard
              key={g.id}
              group={g}
              keepSet={keepSetOf(g)}
              onToggleKeep={(id) => toggleKeep(g, id)}
              onCleanup={() => cleanupGroup(g)}
              busy={ops.isBusy}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function GroupCard({
  group,
  keepSet,
  onToggleKeep,
  onCleanup,
  busy,
}: {
  group: DedupGroup;
  keepSet: Set<string>;
  onToggleKeep: (id: string) => void;
  onCleanup: () => void;
  busy: boolean;
}) {
  const victims = group.items.filter((i) => !keepSet.has(i.id));
  const saved = victims.reduce((acc, i) => acc + (i.size ?? 0), 0);

  // 크게 보기: 그룹 사진들을 전역 ordered로 실어 라이트박스에서 ←/→ 로
  // 그룹 안에서만 넘기며 비교 (i = EXIF/폴더 정보, Delete = 휴지통).
  const openViewer = (id: string) => {
    const s = useTimelineStore.getState();
    s.setOrdered(group.items);
    s.openLightbox(id);
  };

  return (
    <div className="rounded-2xl bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
            group.kind === "exact"
              ? "bg-red-100 text-red-700"
              : "bg-amber-100 text-amber-700"
          }`}
        >
          {group.kind === "exact" ? "정확 중복" : "유사 사진"}
        </span>
        <span className="text-xs text-slate-500">
          {group.items.length}장 중 <b>{keepSet.size}장 보관</b> · 사진 클릭 =
          크게 비교 · 배지 클릭 = 보관↔삭제 전환
        </span>
        <button
          onClick={onCleanup}
          disabled={busy || victims.length === 0}
          className="ml-auto rounded-lg border border-red-200 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40"
        >
          {victims.length}장 정리 · {formatBytes(saved)} 절약
        </button>
      </div>
      <div className="flex flex-wrap gap-3">
        {group.items.map((item) => (
          <DedupThumb
            key={item.id}
            item={item}
            isKept={keepSet.has(item.id)}
            onView={() => openViewer(item.id)}
            onToggleKeep={() => onToggleKeep(item.id)}
          />
        ))}
      </div>
    </div>
  );
}

/** Trim the space prefix noise off a folder path for the card meta line. */
function folderLabel(folder: string | null): string {
  if (!folder) return "폴더 정보 없음";
  return folder === "/" ? "/ (최상위)" : folder;
}

function DedupThumb({
  item,
  isKept,
  onView,
  onToggleKeep,
}: {
  item: DedupItem;
  isKept: boolean;
  onView: () => void;
  onToggleKeep: () => void;
}) {
  return (
    <div className="w-40 text-left">
      <button
        onClick={onView}
        title="클릭해서 크게 비교"
        className="group relative block"
      >
        <img
          src={thumbnailUrl(item.space, item.id, item.cache_key, "sm")}
          alt={item.filename}
          loading="lazy"
          className={`h-36 w-40 rounded-xl object-cover transition-all ${
            isKept
              ? "ring-4 ring-green-500"
              : "opacity-70 grayscale-[25%] group-hover:opacity-100"
          }`}
        />
        <span className="absolute bottom-1.5 right-1.5 rounded-full bg-black/50 px-1.5 py-0.5 text-[10px] text-white opacity-0 transition-opacity group-hover:opacity-100">
          🔍 크게 보기
        </span>
      </button>
      {/* 보관 여부는 사진 열기와 분리된 명시적 배지 토글 (멀티 보관 가능) */}
      <button
        onClick={onToggleKeep}
        title={isKept ? "클릭하면 삭제 예정으로" : "클릭하면 보관으로"}
        className={`mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold transition-colors ${
          isKept
            ? "bg-green-600 text-white hover:bg-green-700"
            : "bg-slate-200 text-slate-500 hover:bg-green-100 hover:text-green-700"
        }`}
      >
        {isKept ? "✓ 보관" : "삭제 예정"}
      </button>
      <p className="mt-1 truncate text-[11px] font-medium text-slate-600" title={item.filename}>
        {item.filename}
      </p>
      <p className="text-[10px] text-slate-500">
        {item.width}×{item.height} · {formatBytes(item.size)} ·{" "}
        {item.taken_at.slice(0, 10)}
      </p>
      <p
        className="truncate text-[10px] text-slate-400"
        title={item.folder ?? undefined}
      >
        📁 {folderLabel(item.folder)}
      </p>
    </div>
  );
}

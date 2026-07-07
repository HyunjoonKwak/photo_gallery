import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoItem } from "../api/types";
import { formatDayHeader } from "../lib/dates";
import { monthLabel } from "../lib/rollup";
import { useTimelineStore, type ViewerLens, type ViewerZoom } from "../store/timeline";
import { GroupedPhotoGrid } from "./timeline/GroupedPhotoGrid";
import { FolderViewerGrid } from "./FolderViewerGrid";
import { TagLensBody } from "./TagLenses";

/** 사진 뷰어 (감상 전용) — 모든 감상 렌즈의 집. 렌즈: 타임라인(연/월/일 줌)·
 * 폴더·사람·장소·비디오. 사람/장소/비디오는 Synology 내장 AI 그룹으로, "앨범"이
 * 아니라 감상 렌즈라 여기로 편입(앨범 영역은 사용자 큐레이션 전용). 순수 뷰어
 * (선택/이동/삭제 없음). */

// 그룹 키/라벨 (모듈 상수 — GroupedPhotoGrid deps 안정).
const yearKey = (d: string) => d.slice(0, 4);
const monthKey = (d: string) => d.slice(0, 7);
const dayKey = (d: string) => d;
const yearLbl = (k: string) => `${k}년`;

/** 타임라인 렌즈 본문 — 연/월/일 줌 바둑판. */
function TimelineLens() {
  const space = useTimelineStore((s) => s.space);
  const zoom = useTimelineStore((s) => s.zoom);
  const focusMonth = useTimelineStore((s) => s.focusMonth);
  const drillTo = useTimelineStore((s) => s.drillTo);
  const openLightbox = useTimelineStore((s) => s.openLightbox);

  const bucketsQuery = useQuery({
    queryKey: ["buckets", space],
    queryFn: () => api.photoBuckets(space),
    staleTime: 5 * 60_000,
  });
  const buckets = bucketsQuery.data?.buckets ?? [];

  const toMonth = (it: PhotoItem) =>
    drillTo({ zoom: "month", month: it.taken_at.slice(0, 7) });
  const toLightbox = (it: PhotoItem) => openLightbox(it.id);

  if (bucketsQuery.isPending)
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        불러오는 중…
      </div>
    );
  if (buckets.length === 0)
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        표시할 사진이 없습니다.
      </div>
    );
  if (zoom === "year")
    return (
      <GroupedPhotoGrid
        key="year"
        space={space}
        buckets={buckets}
        groupKeyOf={yearKey}
        labelOf={yearLbl}
        maxRows={10}
        minTile={58}
        onPhotoClick={toMonth}
      />
    );
  if (zoom === "month")
    return (
      <GroupedPhotoGrid
        key="month"
        space={space}
        buckets={buckets}
        groupKeyOf={monthKey}
        labelOf={monthLabel}
        maxRows={Infinity}
        onPhotoClick={toLightbox}
        scrollToGroup={focusMonth}
      />
    );
  return (
    <GroupedPhotoGrid
      key="day"
      space={space}
      buckets={buckets}
      groupKeyOf={dayKey}
      labelOf={formatDayHeader}
      maxRows={Infinity}
      onPhotoClick={toLightbox}
    />
  );
}

export function ViewerScreen() {
  const viewerLens = useTimelineStore((s) => s.viewerLens);
  return (
    <div className="flex h-full flex-col">
      <LensBar />
      <div className="min-h-0 flex-1">
        {viewerLens === "timeline" && <TimelineLens />}
        {viewerLens === "folder" && <FolderViewerGrid />}
        {(viewerLens === "people" ||
          viewerLens === "places" ||
          viewerLens === "videos") && <TagLensBody lens={viewerLens} />}
      </div>
    </div>
  );
}

const LENSES: { lens: ViewerLens; label: string; icon: string }[] = [
  { lens: "timeline", label: "타임라인", icon: "🕑" },
  { lens: "folder", label: "폴더", icon: "🗂" },
  { lens: "people", label: "사람", icon: "👤" },
  { lens: "places", label: "장소", icon: "📍" },
  { lens: "videos", label: "비디오", icon: "🎬" },
];

const ZOOMS: { z: ViewerZoom; label: string }[] = [
  { z: "year", label: "연" },
  { z: "month", label: "월" },
  { z: "day", label: "일" },
];

/** 렌즈 선택 바 + (타임라인) 연/월/일 줌 + (사람) 그룹 브레드크럼. 좁은 화면에선
 * flex-wrap으로 두 줄 배치(가로 스크롤 금지). */
function LensBar() {
  const viewerLens = useTimelineStore((s) => s.viewerLens);
  const setViewerLens = useTimelineStore((s) => s.setViewerLens);
  const zoom = useTimelineStore((s) => s.zoom);
  const setZoom = useTimelineStore((s) => s.setZoom);
  const focusMonth = useTimelineStore((s) => s.focusMonth);
  const groupId = useTimelineStore((s) => s.groupId);
  const groupLabel = useTimelineStore((s) => s.groupLabel);
  const closeGroup = useTimelineStore((s) => s.closeGroup);

  const crumb = zoom === "month" && focusMonth ? monthLabel(focusMonth) : null;

  return (
    <div
      data-no-boxselect
      className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
    >
      <nav className="flex flex-wrap gap-0.5 rounded-lg bg-slate-100 p-0.5">
        {LENSES.map((v) => (
          <button
            key={v.lens}
            onClick={() => setViewerLens(v.lens)}
            className={`flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              viewerLens === v.lens
                ? "bg-white text-slate-800 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            <span>{v.icon}</span>
            <span className="hidden sm:inline">{v.label}</span>
          </button>
        ))}
      </nav>

      {/* 타임라인 렌즈: 연/월/일 줌 + 월 브레드크럼 */}
      {viewerLens === "timeline" && (
        <>
          <nav className="flex gap-0.5 rounded-lg bg-slate-100 p-0.5">
            {ZOOMS.map((v) => (
              <button
                key={v.z}
                onClick={() => setZoom(v.z)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  zoom === v.z
                    ? "bg-white text-slate-800 shadow-sm"
                    : "text-slate-500 hover:text-slate-700"
                }`}
              >
                {v.label}
              </button>
            ))}
          </nav>
          {crumb && (
            <span className="text-sm font-semibold text-slate-600">{crumb}</span>
          )}
        </>
      )}

      {/* 사람 렌즈: 열린 인물 그룹 브레드크럼 */}
      {viewerLens === "people" && groupId && (
        <>
          <button
            onClick={closeGroup}
            className="rounded px-1.5 py-0.5 text-sm text-blue-600 hover:bg-slate-100"
          >
            ‹ 뒤로
          </button>
          <span className="text-sm font-semibold text-slate-700">
            {groupLabel}
          </span>
        </>
      )}
    </div>
  );
}

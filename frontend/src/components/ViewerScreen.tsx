import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoItem } from "../api/types";
import { formatDayHeader } from "../lib/dates";
import { monthLabel } from "../lib/rollup";
import { useTimelineStore, type ViewerLens, type ViewerZoom } from "../store/timeline";
import { GroupedPhotoGrid } from "./timeline/GroupedPhotoGrid";
import { FolderViewerGrid } from "./FolderViewerGrid";
import { TagLensBody } from "./TagLenses";
import { PhotoLayoutToggle } from "./timeline/PhotoLayoutToggle";
import { QueryErrorState } from "./QueryErrorState";

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
  if (bucketsQuery.isError && buckets.length === 0)
    return (
      <QueryErrorState
        message="사진 타임라인을 불러오지 못했습니다."
        onRetry={() => void bucketsQuery.refetch()}
      />
    );
  // 빈 상태에 다음 행동 안내(IA 4단계) — 앱이 스스로 개념을 설명한다.
  if (buckets.length === 0)
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-slate-400">
        <p className="text-3xl">🖼</p>
        <p className="text-sm font-medium text-slate-500">
          {space === "team" ? "가족 사진이 아직 없어요" : "아직 사진이 없어요"}
        </p>
        <p className="max-w-xs text-xs leading-relaxed">
          {space === "team"
            ? "Photo Desk에서 가족 사진으로 발행하면 온 가족이 여기서 함께 볼 수 있어요."
            : "Photo Desk에서 내 사진으로 정리한 사진이 여기에 표시됩니다."}
        </p>
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
        onTopGroupChange={useTimelineStore.getState().setVisibleGroupLabel}
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

const LENSES: {
  lens: ViewerLens;
  label: string;
  shortLabel: string;
  icon: string;
}[] = [
  { lens: "timeline", label: "타임라인", shortLabel: "시간", icon: "🕑" },
  { lens: "folder", label: "폴더별 보기", shortLabel: "폴더", icon: "📂" },
  { lens: "people", label: "사람", shortLabel: "사람", icon: "👤" },
  { lens: "places", label: "장소", shortLabel: "장소", icon: "📍" },
  { lens: "videos", label: "비디오", shortLabel: "영상", icon: "🎬" },
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

  const visibleGroupLabel = useTimelineStore((s) => s.visibleGroupLabel);
  // 크럼은 실제 뷰포트 상단 그룹을 따른다(스크롤과 타이틀 불일치 해소).
  const crumb =
    zoom === "month"
      ? (visibleGroupLabel ?? (focusMonth ? monthLabel(focusMonth) : null))
      : null;
  const showLayout =
    viewerLens === "timeline" ||
    viewerLens === "videos" ||
    (viewerLens === "people" && groupId != null);

  return (
    <div
      data-no-boxselect
      className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
    >
      <nav
        aria-label="사진 보기 방식"
        className="flex flex-wrap gap-0.5 rounded-lg bg-slate-100 p-0.5"
      >
        {LENSES.map((v) => (
          <button
            type="button"
            key={v.lens}
            onClick={() => setViewerLens(v.lens)}
            aria-label={v.label}
            aria-pressed={viewerLens === v.lens}
            className={`flex min-h-10 items-center gap-0.5 rounded-md px-2 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:min-h-0 sm:flex-row sm:gap-1 sm:px-2.5 ${
              viewerLens === v.lens
                ? "bg-white text-slate-800 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            <span aria-hidden>{v.icon}</span>
            <span className="text-[10px] leading-none sm:hidden">
              {v.shortLabel}
            </span>
            <span className="hidden sm:inline">{v.label}</span>
          </button>
        ))}
      </nav>

      {/* 타임라인 렌즈: 연/월/일 줌 + 월 브레드크럼 */}
      {viewerLens === "timeline" && (
        <>
          <nav
            aria-label="타임라인 확대 단계"
            className="flex gap-0.5 rounded-lg bg-slate-100 p-0.5"
          >
            {ZOOMS.map((v) => (
              <button
                type="button"
                key={v.z}
                onClick={() => setZoom(v.z)}
                aria-pressed={zoom === v.z}
                className={`min-h-10 rounded-md px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:min-h-0 ${
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

      {/* 실제 사진 격자가 있는 화면에서만 배치 전환을 노출한다. */}
      {showLayout && <PhotoLayoutToggle className="ml-auto" />}
    </div>
  );
}

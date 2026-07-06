import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { PhotoItem } from "../api/types";
import { formatDayHeader } from "../lib/dates";
import { monthLabel } from "../lib/rollup";
import { useTimelineStore, type ViewerZoom } from "../store/timeline";
import { GroupedPhotoGrid } from "./timeline/GroupedPhotoGrid";
import { FolderViewerGrid } from "./FolderViewerGrid";

/** 사진 뷰어 (감상 전용) — Synology Photos 스타일 연/월/일/폴더 줌.
 * 연=연도별 작은 타일 10줄 미리보기(+"n장 더"), 월·일=해당 월/일 사진 전부.
 * 연 뷰 사진 탭→그 사진의 월로(전체 월 연속에서 스크롤), 월·일 뷰 사진 탭→
 * 라이트박스. 순수 뷰어(선택/이동/삭제 없음). */

// 그룹 키/라벨 (모듈 상수 — GroupedPhotoGrid deps 안정).
const yearKey = (d: string) => d.slice(0, 4);
const monthKey = (d: string) => d.slice(0, 7);
const dayKey = (d: string) => d;
const yearLbl = (k: string) => `${k}년`;

export function ViewerScreen() {
  const space = useTimelineStore((s) => s.space);
  const zoom = useTimelineStore((s) => s.zoom);
  const focusMonth = useTimelineStore((s) => s.focusMonth);
  const drillTo = useTimelineStore((s) => s.drillTo);
  const openLightbox = useTimelineStore((s) => s.openLightbox);

  const bucketsQuery = useQuery({
    queryKey: ["buckets", space],
    queryFn: () => api.photoBuckets(space),
    staleTime: 5 * 60_000,
    enabled: zoom !== "folder", // 폴더 뷰는 buckets 불필요
  });
  const buckets = bucketsQuery.data?.buckets ?? [];

  const toMonth = (it: PhotoItem) =>
    drillTo({ zoom: "month", month: it.taken_at.slice(0, 7) });
  const toLightbox = (it: PhotoItem) => openLightbox(it.id);

  return (
    <div className="flex h-full flex-col">
      <ZoomBar />
      <div className="min-h-0 flex-1">
        {zoom === "folder" ? (
          <FolderViewerGrid />
        ) : bucketsQuery.isPending ? (
          <div className="flex h-full items-center justify-center text-slate-400">
            불러오는 중…
          </div>
        ) : buckets.length === 0 ? (
          <div className="flex h-full items-center justify-center text-slate-400">
            표시할 사진이 없습니다.
          </div>
        ) : zoom === "year" ? (
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
        ) : zoom === "month" ? (
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
        ) : (
          <GroupedPhotoGrid
            key="day"
            space={space}
            buckets={buckets}
            groupKeyOf={dayKey}
            labelOf={formatDayHeader}
            maxRows={Infinity}
            onPhotoClick={toLightbox}
          />
        )}
      </div>
    </div>
  );
}

const ZOOMS: { z: ViewerZoom; label: string }[] = [
  { z: "year", label: "연" },
  { z: "month", label: "월" },
  { z: "day", label: "일" },
  { z: "folder", label: "폴더" },
];

function ZoomBar() {
  const zoom = useTimelineStore((s) => s.zoom);
  const setZoom = useTimelineStore((s) => s.setZoom);
  const focusMonth = useTimelineStore((s) => s.focusMonth);
  const crumb =
    zoom === "month" && focusMonth ? monthLabel(focusMonth) : null;
  return (
    <div
      data-no-boxselect
      className="flex shrink-0 items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 sm:px-4"
    >
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
      {crumb && <span className="text-sm font-semibold text-slate-600">{crumb}</span>}
    </div>
  );
}

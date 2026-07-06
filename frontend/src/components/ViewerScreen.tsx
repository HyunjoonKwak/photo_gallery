import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api } from "../api/client";
import type { PhotoBucket, PhotoItem, Space } from "../api/types";
import {
  rollupMonths,
  rollupYears,
  yearLabel,
  monthLabel,
  type RollupGroup,
} from "../lib/rollup";
import { useTimelineStore, type ViewerZoom } from "../store/timeline";
import { Thumb } from "./timeline/Thumb";

/** 사진 뷰어 (감상 전용) — Synology Photos 스타일 연/월/일/폴더 줌.
 * 연 카드 탭→월, 월 카드 탭→일, 일 뷰에서 사진 탭→라이트박스(좌우 넘기기).
 * 선택/이동/삭제 없음(정리는 폴더 분류에서). */
export function ViewerScreen() {
  const space = useTimelineStore((s) => s.space);
  const zoom = useTimelineStore((s) => s.zoom);
  const focusYear = useTimelineStore((s) => s.focusYear);
  const focusMonth = useTimelineStore((s) => s.focusMonth);

  const bucketsQuery = useQuery({
    queryKey: ["buckets", space],
    queryFn: () => api.photoBuckets(space),
    staleTime: 5 * 60_000,
  });
  const buckets = bucketsQuery.data?.buckets ?? [];

  if (bucketsQuery.isPending) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        불러오는 중…
      </div>
    );
  }
  if (buckets.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        표시할 사진이 없습니다.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <ZoomBar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        {zoom === "year" && <YearView buckets={buckets} space={space} />}
        {zoom === "month" && (
          <MonthView buckets={buckets} space={space} year={focusYear} />
        )}
        {zoom === "day" && (
          <DayView buckets={buckets} space={space} month={focusMonth} />
        )}
        {zoom === "folder" && (
          <p className="p-8 text-center text-sm text-slate-400">
            폴더별 보기는 준비 중입니다. 폴더 정리는 상단 "폴더 분류"에서
            할 수 있습니다.
          </p>
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
  const focusYear = useTimelineStore((s) => s.focusYear);
  const focusMonth = useTimelineStore((s) => s.focusMonth);
  const crumb =
    zoom === "month" && focusYear
      ? yearLabel(focusYear)
      : zoom === "day" && focusMonth
        ? monthLabel(focusMonth)
        : null;
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

/** 연/월 대표 커버 타일 — 그룹의 최신일 첫 사진을 커버로(가시 여부와 무관하게
 * 그룹 수가 적어 즉시 프리페치). */
function CoverTile({
  space,
  group,
  label,
  onClick,
}: {
  space: Space;
  group: RollupGroup;
  label: string;
  onClick: () => void;
}) {
  const q = useQuery({
    queryKey: ["bucket", space, group.coverDay],
    queryFn: () => api.bucketItems(space, group.coverDay),
    staleTime: Infinity,
  });
  const cover = q.data?.items?.[0];
  return (
    <button
      onClick={onClick}
      className="group relative aspect-square overflow-hidden rounded-xl bg-slate-200 text-left"
    >
      {cover && <Thumb item={cover} space={space} rounded="rounded-xl" />}
      <div className="absolute inset-0 bg-gradient-to-t from-black/65 via-black/10 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 p-2.5 text-white">
        <div className="text-sm font-bold drop-shadow">{label}</div>
        <div className="text-[11px] opacity-90">
          {group.count.toLocaleString()}장
        </div>
      </div>
    </button>
  );
}

function YearView({ buckets, space }: { buckets: PhotoBucket[]; space: Space }) {
  const drillTo = useTimelineStore((s) => s.drillTo);
  const years = useMemo(() => rollupYears(buckets), [buckets]);
  return (
    <div
      className="grid gap-3 p-4"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))" }}
    >
      {years.map((g) => (
        <CoverTile
          key={g.key}
          space={space}
          group={g}
          label={yearLabel(g.key)}
          onClick={() => drillTo({ zoom: "month", year: g.key })}
        />
      ))}
    </div>
  );
}

function MonthView({
  buckets,
  space,
  year,
}: {
  buckets: PhotoBucket[];
  space: Space;
  year: string | null;
}) {
  const drillTo = useTimelineStore((s) => s.drillTo);
  const months = useMemo(
    () => rollupMonths(buckets, year ?? undefined),
    [buckets, year],
  );
  return (
    <div
      className="grid gap-3 p-4"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))" }}
    >
      {months.map((g) => (
        <CoverTile
          key={g.key}
          space={space}
          group={g}
          label={monthLabel(g.key)}
          onClick={() => drillTo({ zoom: "day", month: g.key })}
        />
      ))}
    </div>
  );
}

/** 일 뷰 — 한 달(month)의 사진을 균일 정사각 그리드로, 행 단위 가상화(큰 달은
 * 수천 장). 사진 탭 = 라이트박스(그 달 전체를 setOrdered 해 좌우 넘기기). */
function DayView({
  buckets,
  space,
  month,
}: {
  buckets: PhotoBucket[];
  space: Space;
  month: string | null;
}) {
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const openLightbox = useTimelineStore((s) => s.openLightbox);
  // month 미지정(토글로 "일" 직행)이면 가장 최근 달.
  const activeMonth = month ?? rollupMonths(buckets)[0]?.key ?? null;
  const days = useMemo(
    () =>
      activeMonth
        ? buckets.filter((b) => b.day.slice(0, 7) === activeMonth).map((b) => b.day)
        : [],
    [buckets, activeMonth],
  );
  const itemQueries = useQueries({
    queries: days.map((day) => ({
      queryKey: ["bucket", space, day],
      queryFn: () => api.bucketItems(space, day),
      staleTime: Infinity,
    })),
  });
  const loadedSig = itemQueries.map((q) => q.data?.day ?? "").join("|");
  const items = useMemo(() => {
    const out: PhotoItem[] = [];
    for (const q of itemQueries) {
      if (q.data) for (const it of q.data.items) out.push({ ...it, space });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedSig, space]);

  useEffect(() => {
    setOrdered(items);
  }, [items, setOrdered]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const GAP = 4;
  const MIN_TILE = 116;
  const cols = Math.max(1, Math.floor((width + GAP) / (MIN_TILE + GAP)));
  const tile = cols > 0 ? (width - GAP * (cols - 1)) / cols : MIN_TILE;
  const rowCount = Math.ceil(items.length / cols);

  const virtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => tile + GAP,
    overscan: 6,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [tile, rowCount, virtualizer]);

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto p-1">
      <div
        style={{
          height: virtualizer.getTotalSize(),
          position: "relative",
          width: "100%",
        }}
      >
        {virtualizer.getVirtualItems().map((row) => {
          const start = row.index * cols;
          const rowItems = items.slice(start, start + cols);
          return (
            <div
              key={row.key}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${row.start}px)`,
                display: "flex",
                gap: GAP,
              }}
            >
              {rowItems.map((it) => (
                <button
                  key={it.id}
                  data-photo-id={it.id}
                  onClick={() => openLightbox(it.id)}
                  style={{ width: tile, height: tile }}
                  className="overflow-hidden rounded-sm outline-none"
                >
                  <Thumb item={it} space={space} />
                </button>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

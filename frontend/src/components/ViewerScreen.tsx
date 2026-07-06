import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api } from "../api/client";
import type { PhotoBucket, PhotoItem, Space } from "../api/types";
import { formatDayHeader } from "../lib/dates";
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
      <div className="min-h-0 flex-1">
        {zoom === "year" && (
          <div className="h-full overflow-y-auto">
            <YearView buckets={buckets} space={space} />
          </div>
        )}
        {zoom === "month" && (
          <div className="h-full overflow-y-auto">
            <MonthView buckets={buckets} space={space} focusYear={focusYear} />
          </div>
        )}
        {zoom === "day" && (
          <DayView buckets={buckets} space={space} focusMonth={focusMonth} />
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
  anchorId,
}: {
  space: Space;
  group: RollupGroup;
  label: string;
  onClick: () => void;
  /** 연→월 드릴 시 그 연도로 스크롤하기 위한 앵커 id(있으면 이 카드가 대상). */
  anchorId?: string;
}) {
  const q = useQuery({
    queryKey: ["bucket", space, group.coverDay],
    queryFn: () => api.bucketItems(space, group.coverDay),
    staleTime: Infinity,
  });
  const cover = q.data?.items?.[0];
  return (
    <button
      id={anchorId}
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
  focusYear,
}: {
  buckets: PhotoBucket[];
  space: Space;
  focusYear: string | null;
}) {
  const drillTo = useTimelineStore((s) => s.drillTo);
  // 전체 월을 보여준다(연도 스코프 X — 연처럼 전체 줌). 연 뷰에서 온 경우
  // 그 연도의 첫 월로 스크롤만 맞춘다.
  const months = useMemo(() => rollupMonths(buckets), [buckets]);
  const anchorKey = focusYear
    ? months.find((m) => m.key.slice(0, 4) === focusYear)?.key
    : null;
  // 연→월 드릴 시 그 연도 첫 월로 스크롤 (레이아웃 안정 후 DOM id로 — ref
  // 타이밍 회피). focusYear 없으면(토글 직접) 스크롤 안 함.
  useEffect(() => {
    if (!anchorKey) return;
    const t = setTimeout(() => {
      document
        .getElementById(`mon-${anchorKey}`)
        ?.scrollIntoView({ block: "start" });
    }, 100);
    return () => clearTimeout(t);
  }, [anchorKey]);
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
          anchorId={g.key === anchorKey ? `mon-${g.key}` : undefined}
        />
      ))}
    </div>
  );
}

/** 일 뷰 — 전체 아카이브를 날짜(day)별 헤더 + 그날 사진 정사각 그리드로,
 * 연속 스크롤. 뷰포트에 다가온 날만 지연 로드하고 행 단위로 가상화(6만 장
 * 대비). focusMonth가 있으면 그 달로 초기 스크롤. 사진 탭 = 라이트박스(로드된
 * 사진을 setOrdered 해 좌우 넘기기). */
const HEADER_H = 40;
const GAP = 4;
const MIN_TILE = 116;

type DayRow =
  | { kind: "header"; day: string; key: string }
  | { kind: "photos"; day: string; items: PhotoItem[]; key: string }
  | { kind: "placeholder"; day: string; key: string; cols: number };

function DayView({
  buckets,
  space,
  focusMonth,
}: {
  buckets: PhotoBucket[];
  space: Space;
  focusMonth: string | null;
}) {
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  const openLightbox = useTimelineStore((s) => s.openLightbox);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const setRefs = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    setScrollEl(el);
  }, []);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = scrollEl;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(Math.floor(el.clientWidth) - 8));
    ro.observe(el);
    return () => ro.disconnect();
  }, [scrollEl]);

  const cols = Math.max(1, Math.floor((width + GAP) / (MIN_TILE + GAP)));
  const tile = cols > 0 ? (width - GAP * (cols - 1)) / cols : MIN_TILE;

  const [requestedDays, setRequestedDays] = useState<string[]>([]);
  const itemQueries = useQueries({
    queries: requestedDays.map((day) => ({
      queryKey: ["bucket", space, day],
      queryFn: () => api.bucketItems(space, day),
      staleTime: Infinity,
    })),
  });
  const loadedSig = itemQueries.map((q) => q.data?.day ?? "").join("|");
  const loaded = useMemo(() => {
    const m = new Map<string, PhotoItem[]>();
    for (const q of itemQueries) {
      if (q.data) m.set(q.data.day, q.data.items.map((it) => ({ ...it, space })));
    }
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedSig, space]);

  // 로드된 사진을 날짜 순서대로 orderedItems → 라이트박스 좌우 넘기기.
  const orderedItems = useMemo(() => {
    const out: PhotoItem[] = [];
    for (const b of buckets) {
      const its = loaded.get(b.day);
      if (its) out.push(...its);
    }
    return out;
  }, [buckets, loaded]);
  useEffect(() => {
    setOrdered(orderedItems);
  }, [orderedItems, setOrdered]);

  // 행 모델: 각 day = 헤더 1행 + 사진 행들(로드) 또는 placeholder 행들(미로드).
  const rows = useMemo<DayRow[]>(() => {
    const out: DayRow[] = [];
    for (const b of buckets) {
      out.push({ kind: "header", day: b.day, key: `h-${b.day}` });
      const its = loaded.get(b.day);
      const rowN = Math.max(1, Math.ceil(b.count / cols));
      if (its) {
        for (let i = 0; i < Math.ceil(its.length / cols); i++) {
          out.push({
            kind: "photos",
            day: b.day,
            items: its.slice(i * cols, i * cols + cols),
            key: `p-${b.day}-${i}`,
          });
        }
      } else {
        for (let i = 0; i < rowN; i++) {
          out.push({
            kind: "placeholder",
            day: b.day,
            key: `x-${b.day}-${i}`,
            cols,
          });
        }
      }
    }
    return out;
  }, [buckets, loaded, cols]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) =>
      rows[i]?.kind === "header" ? HEADER_H : tile + GAP,
    overscan: 8,
    getItemKey: (i) => rows[i]?.key ?? i,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [rows, tile, virtualizer]);

  // 가시(overscan 포함) 행의 day를 요청.
  const virtualItems = virtualizer.getVirtualItems();
  useEffect(() => {
    const have = new Set(requestedDays);
    const need: string[] = [];
    for (const v of virtualItems) {
      const day = rows[v.index]?.day;
      if (day && !have.has(day) && !need.includes(day)) need.push(day);
    }
    if (need.length) setRequestedDays((prev) => [...prev, ...need]);
  });

  // focusMonth로 초기 스크롤(연→월→일 드릴 시 그 달 헤더로).
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    if (!focusMonth || scrolledFor.current === focusMonth) return;
    const idx = rows.findIndex(
      (r) => r.kind === "header" && r.day.slice(0, 7) === focusMonth,
    );
    if (idx >= 0) {
      virtualizer.scrollToIndex(idx, { align: "start" });
      scrolledFor.current = focusMonth;
    }
  }, [focusMonth, rows, virtualizer]);

  if (buckets.length === 0) {
    return (
      <p className="p-8 text-center text-sm text-slate-400">사진이 없습니다.</p>
    );
  }

  return (
    <div ref={setRefs} className="h-full overflow-y-auto px-1">
      <div
        style={{
          height: virtualizer.getTotalSize(),
          position: "relative",
          width: "100%",
        }}
      >
        {virtualItems.map((v) => {
          const row = rows[v.index];
          if (!row) return null;
          return (
            <div
              key={v.key}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${v.start}px)`,
              }}
            >
              {row.kind === "header" && (
                <div className="flex items-end px-2 pb-1 pt-3 text-sm font-semibold text-slate-700">
                  {formatDayHeader(row.day)}
                </div>
              )}
              {row.kind === "photos" && (
                <div style={{ display: "flex", gap: GAP }}>
                  {row.items.map((it) => (
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
              )}
              {row.kind === "placeholder" && (
                <div style={{ display: "flex", gap: GAP }}>
                  {Array.from({ length: row.cols }, (_, i) => (
                    <div
                      key={i}
                      style={{ width: tile, height: tile }}
                      className="rounded-sm bg-slate-200/70"
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

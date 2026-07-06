import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQueries } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api } from "../../api/client";
import type { PhotoBucket, PhotoItem, Space } from "../../api/types";
import { useTimelineStore } from "../../store/timeline";
import { Thumb } from "./Thumb";
import { Scrubber, type ScrubberMarker } from "./Scrubber";

const HEADER_H = 40;
const GAP = 4;
const DEFAULT_MIN_TILE = 116;

type Row =
  | { kind: "header"; key: string; groupKey: string; label: string }
  | { kind: "photos"; key: string; groupKey: string; items: PhotoItem[] }
  | { kind: "placeholder"; key: string; groupKey: string; day: string; cols: number }
  | { kind: "more"; key: string; groupKey: string; hidden: number };

interface Group {
  key: string;
  label: string;
  days: string[]; // 최신순
  total: number; // 그룹 전체 사진 수
}

/** 그룹(연/월/일) 헤더 + 그 그룹 사진 썸네일 바둑판. 연·월은 maxRows줄만
 * 미리보기(+"n장 더"), 일은 전부. 뷰포트에 다가온 그룹만 지연 로드하고 행
 * 단위로 가상화한다. 사진 탭 = onPhotoClick(연→월 드릴 / 월·일→라이트박스). */
export function GroupedPhotoGrid({
  space,
  buckets,
  groupKeyOf,
  labelOf,
  maxRows,
  minTile = DEFAULT_MIN_TILE,
  onPhotoClick,
  scrollToGroup,
}: {
  space: Space;
  buckets: PhotoBucket[];
  groupKeyOf: (day: string) => string;
  labelOf: (groupKey: string) => string;
  maxRows: number; // Infinity = 그룹 전부
  minTile?: number; // 타일 최소 폭(px) — 열 수/타일 크기 결정
  onPhotoClick: (item: PhotoItem) => void;
  scrollToGroup?: string | null;
}) {
  const setOrdered = useTimelineStore((s) => s.setOrdered);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const setRefs = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    setScrollEl(el);
  }, []);
  const [width, setWidth] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  useLayoutEffect(() => {
    const el = scrollEl;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setWidth(Math.floor(el.clientWidth) - 8);
      setViewportH(el.clientHeight);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [scrollEl]);
  const cols = Math.max(1, Math.floor((width + GAP) / (minTile + GAP)));
  const tile = cols > 0 ? (width - GAP * (cols - 1)) / cols : minTile;

  // buckets → 그룹 (최신순 유지).
  const groups = useMemo<Group[]>(() => {
    const map = new Map<string, Group>();
    for (const b of buckets) {
      const key = groupKeyOf(b.day);
      const g = map.get(key);
      if (g) {
        g.days.push(b.day);
        g.total += b.count;
      } else {
        map.set(key, {
          key,
          label: labelOf(key),
          days: [b.day],
          total: b.count,
        });
      }
    }
    return [...map.values()];
  }, [buckets, groupKeyOf, labelOf]);

  // 각 그룹의 "미리보기 days" = maxRows*cols장 채울 만큼(bucket count 누적).
  const bucketCount = useMemo(() => {
    const m = new Map<string, number>();
    for (const b of buckets) m.set(b.day, b.count);
    return m;
  }, [buckets]);
  const previewDaysOf = useCallback(
    (g: Group): string[] => {
      if (maxRows === Infinity) return g.days;
      const cap = maxRows * cols;
      const out: string[] = [];
      let acc = 0;
      for (const d of g.days) {
        out.push(d);
        acc += bucketCount.get(d) ?? 0;
        if (acc >= cap) break;
      }
      return out;
    },
    [maxRows, cols, bucketCount],
  );

  // 지연 로드: 가시 그룹의 미리보기 days. (중복 제거 — useQueries에 같은
  // queryKey가 두 번 들어가면 React Query가 "Duplicate Queries" 경고.)
  const [requestedDays, setRequestedDays] = useState<string[]>([]);
  const uniqueDays = useMemo(() => [...new Set(requestedDays)], [requestedDays]);
  const itemQueries = useQueries({
    queries: uniqueDays.map((day) => ({
      queryKey: ["bucket", space, day],
      queryFn: () => api.bucketItems(space, day),
      staleTime: Infinity,
    })),
  });
  const loadedSig = itemQueries.map((q) => q.data?.day ?? "").join("|");
  const loaded = useMemo(() => {
    const m = new Map<string, PhotoItem[]>();
    for (const q of itemQueries) {
      if (q.data)
        m.set(q.data.day, q.data.items.map((it) => ({ ...it, space })));
    }
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedSig, space]);

  // 그룹별 미리보기 사진(로드된 것) + 행 모델.
  const { rows, ordered } = useMemo(() => {
    const rows: Row[] = [];
    const ordered: PhotoItem[] = [];
    for (const g of groups) {
      rows.push({
        kind: "header",
        key: `h-${g.key}`,
        groupKey: g.key,
        label: g.label,
      });
      const pdays = previewDaysOf(g);
      const anyLoaded = pdays.some((d) => loaded.has(d));
      if (anyLoaded) {
        const items: PhotoItem[] = [];
        for (const d of pdays) {
          const its = loaded.get(d);
          if (its) items.push(...its);
        }
        const shown =
          maxRows === Infinity ? items : items.slice(0, maxRows * cols);
        ordered.push(...shown);
        for (let i = 0; i < Math.ceil(shown.length / cols); i++) {
          rows.push({
            kind: "photos",
            key: `p-${g.key}-${i}`,
            groupKey: g.key,
            items: shown.slice(i * cols, i * cols + cols),
          });
        }
        const hidden = g.total - shown.length;
        if (maxRows !== Infinity && hidden > 0) {
          rows.push({ kind: "more", key: `m-${g.key}`, groupKey: g.key, hidden });
        }
      } else {
        // 미로드: 예상 행 수만큼 placeholder (첫 미리보기 day 기준).
        const est = Math.min(
          maxRows === Infinity ? Infinity : maxRows,
          Math.max(1, Math.ceil((bucketCount.get(pdays[0]) ?? cols) / cols)),
        );
        for (let i = 0; i < (est === Infinity ? 1 : est); i++) {
          rows.push({
            kind: "placeholder",
            key: `x-${g.key}-${i}`,
            groupKey: g.key,
            day: pdays[0],
            cols,
          });
        }
      }
    }
    return { rows, ordered };
  }, [groups, previewDaysOf, loaded, cols, maxRows, bucketCount]);

  useEffect(() => {
    setOrdered(ordered);
  }, [ordered, setOrdered]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => {
      const r = rows[i];
      if (r?.kind === "header") return HEADER_H;
      if (r?.kind === "more") return 28;
      return tile + GAP;
    },
    overscan: 8,
    getItemKey: (i) => rows[i]?.key ?? i,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [rows, tile, virtualizer]);

  const virtualItems = virtualizer.getVirtualItems();

  // 화면에 보이는 그룹의 미리보기 days를 요청. placeholder 행이 아니라 가시
  // "그룹" 기준이라, 첫 day 로드로 photos 행으로 전환된 뒤에도(그리고 cols가
  // 늘어 cap이 커진 뒤에도) 5줄을 채울 나머지 day를 계속 요청한다.
  useEffect(() => {
    const have = new Set(requestedDays);
    const visibleGroups = new Set<string>();
    for (const v of virtualItems) {
      const r = rows[v.index];
      if (r) visibleGroups.add(r.groupKey);
    }
    const need: string[] = [];
    for (const gkey of visibleGroups) {
      const g = groups.find((gr) => gr.key === gkey);
      if (!g) continue;
      for (const d of previewDaysOf(g)) {
        if (!have.has(d) && !need.includes(d)) need.push(d);
      }
    }
    if (need.length) setRequestedDays((prev) => [...prev, ...need]);
  });

  // scrollToGroup 대상 그룹의 미리보기 days를 선요청(화면 밖이라 placeholder
  // 요청 경로를 못 타는 경우 대비 — 로드돼야 높이가 실측되어 스크롤이 정확).
  useEffect(() => {
    if (!scrollToGroup) return;
    const g = groups.find((gr) => gr.key === scrollToGroup);
    if (!g) return;
    const days = previewDaysOf(g);
    setRequestedDays((prev) => {
      const have = new Set(prev);
      const add = days.filter((d) => !have.has(d));
      return add.length ? [...prev, ...add] : prev;
    });
  }, [scrollToGroup, groups, previewDaysOf]);

  // scrollToGroup으로 초기 스크롤(연→월 드릴 등). 가상화 + 동적 높이라
  // placeholder 추정 위에서 한 번 스크롤하면 어긋남 → 대상 그룹이 로드돼
  // 높이가 실측될 때까지 rows/loaded 변화마다 재스크롤.
  const scrolledFor = useRef<string | null>(null);
  useEffect(() => {
    if (!scrollToGroup || scrolledFor.current === scrollToGroup) return;
    const idx = rows.findIndex(
      (r) => r.kind === "header" && r.groupKey === scrollToGroup,
    );
    if (idx < 0) return;
    virtualizer.scrollToIndex(idx, { align: "start" });
    const g = groups.find((gr) => gr.key === scrollToGroup);
    const firstDay = g ? previewDaysOf(g)[0] : null;
    // 높이가 실측된 뒤에야 "완료" 표시(그 전엔 loaded 갱신마다 재스크롤).
    if (firstDay && loaded.has(firstDay)) scrolledFor.current = scrollToGroup;
  }, [scrollToGroup, rows, loaded, groups, previewDaysOf, virtualizer]);

  // 사이드 스크러버용 월 마커: 그룹 헤더가 시작하는 콘텐츠 offset. 그룹 키
  // 길이로 줌 판별(연 "2025" / 월 "2025-12" / 일 "2025-12-30") → 월(YYYY-MM)
  // 단위로 중복 제거. offset은 가상화 실측(getOffsetForIndex)이라 스크롤과 일치.
  const totalSize = virtualizer.getTotalSize();
  const markers = useMemo<ScrubberMarker[]>(() => {
    const out: ScrubberMarker[] = [];
    let last = "";
    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.kind !== "header") continue;
      const k = r.groupKey;
      const month = k.length <= 4 ? `${k}-01` : k.slice(0, 7);
      if (month === last) continue;
      last = month;
      const off = virtualizer.getOffsetForIndex(i, "start");
      const offset =
        typeof off === "number" ? off : Array.isArray(off) ? off[0] : 0;
      out.push({ month, offset });
    }
    return out;
    // totalSize를 dep에 넣어 로드·측정으로 레이아웃이 바뀌면 재계산.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, totalSize, viewportH]);

  if (groups.length === 0) {
    return (
      <p className="p-8 text-center text-sm text-slate-400">사진이 없습니다.</p>
    );
  }

  return (
    <div className="relative h-full">
      <div
        ref={setRefs}
        className="h-full overflow-y-auto px-1"
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
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
                  {row.label}
                </div>
              )}
              {row.kind === "photos" && (
                <div style={{ display: "flex", gap: GAP }}>
                  {row.items.map((it) => (
                    <button
                      key={it.id}
                      data-photo-id={it.id}
                      onClick={() => onPhotoClick(it)}
                      style={{ width: tile, height: tile }}
                      className="overflow-hidden rounded-sm outline-none"
                    >
                      <Thumb item={it} space={space} />
                    </button>
                  ))}
                </div>
              )}
              {row.kind === "more" && (
                <div className="px-2 pb-1 text-xs text-slate-400">
                  이 그룹에 {row.hidden.toLocaleString()}장 더 —
                  아래 줌에서 전체 보기
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
      <Scrubber
        markers={markers}
        totalHeight={totalSize}
        viewportHeight={viewportH}
        scrollTop={scrollTop}
        onJump={(offset) => {
          const el = scrollRef.current;
          if (el) el.scrollTop = offset;
        }}
      />
    </div>
  );
}

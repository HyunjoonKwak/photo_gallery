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
import { groupLoadedDayRuns } from "../../lib/groupDayRuns";
import { useTimelineStore } from "../../store/timeline";
import { layoutBucket, type CellLayout } from "../../lib/rowModel";
import { Thumb } from "./Thumb";
import { Scrubber, type ScrubberMarker } from "./Scrubber";

const HEADER_H = 40;
const GAP = 4;
const DEFAULT_MIN_TILE = 116;

type Row =
  | { kind: "header"; key: string; groupKey: string; label: string }
  | {
      kind: "photos";
      key: string;
      groupKey: string;
      day: string;
      items: PhotoItem[];
      /** 비율 보기일 때의 배치. 없으면 정사각 바둑판. */
      cells?: CellLayout[];
      /** 비율 보기 행의 실제 높이(px). 없으면 tile + GAP. */
      height?: number;
    }
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
  onTopGroupChange,
}: {
  space: Space;
  buckets: PhotoBucket[];
  groupKeyOf: (day: string) => string;
  labelOf: (groupKey: string) => string;
  maxRows: number; // Infinity = 그룹 전부
  minTile?: number; // 타일 최소 폭(px) — 열 수/타일 크기 결정
  onPhotoClick: (item: PhotoItem) => void;
  scrollToGroup?: string | null;
  /** 뷰포트 최상단에 실제로 보이는 그룹 라벨 보고(월뷰 크럼 동기화). */
  onTopGroupChange?: (label: string | null) => void;
}) {
  const setOrdered = useTimelineStore((s) => s.setOrdered);
  // 「비율」 보기 — 정사각 크롭 대신 원본 비율을 지킨다. 타임라인은 그룹별
  // 지연 로드 + 행 가상화라 열 기반 메이슨리를 넣을 수 없다(배치가 그룹이
  // 채워질 때마다 통째로 흔들린다). 대신 justified 로 **행 구조를 지키면서**
  // 크롭만 없앤다 — 세로 사진이 잘리지 않는다는 목적은 같다.
  const fit = useTimelineStore((s) => s.photoLayout);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const setScrollRefs = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    setScrollEl(el);
  }, []);
  // 폭은 스크러버 거터(pr-12)를 뺀 "안쪽" 박스에서 측정한다. 패딩 포함
  // 컨테이너를 재면 열이 실제보다 넓게 잡혀 사진이 우측 라벨 밑으로 넘친다.
  const [contentEl, setContentEl] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);
  useLayoutEffect(() => {
    if (!scrollEl) return;
    const ro = new ResizeObserver(() => setViewportH(scrollEl.clientHeight));
    ro.observe(scrollEl);
    return () => ro.disconnect();
  }, [scrollEl]);
  useLayoutEffect(() => {
    if (!contentEl) return;
    const ro = new ResizeObserver(() =>
      setWidth(Math.floor(contentEl.clientWidth)),
    );
    ro.observe(contentEl);
    return () => ro.disconnect();
  }, [contentEl]);
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

  // 그룹별 행 모델. 아직 읽지 않은 날짜도 bucket count만큼 자리를 미리
  // 잡는다. 예전에는 월 전체를 한 줄로만 잡아 overscan 안에 여러 달이 들어와
  // 수백 개 날짜 요청이 동시에 시작됐고, 첫 날짜가 오면 높이가 다시 무너졌다.
  // 날짜별 placeholder는 스크롤 높이를 안정시키고 실제 보이는 날짜만 요청하게
  // 한다(B-1 count-first 레이아웃의 의도).
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
      let rowBudget = maxRows;
      let represented = 0;
      const dayRuns = groupLoadedDayRuns(
        pdays,
        loaded,
        (day) => bucketCount.get(day) ?? cols,
      );
      for (const run of dayRuns) {
        if (rowBudget <= 0) break;
        if (run.kind === "loaded") {
          const items = run.items;
          const runKey = `${run.days[0]}-${run.days[run.days.length - 1]}`;
          if (fit === "masonry" && width > 0) {
            // 연·월 그룹에는 날짜 사이 헤더가 없으므로, 인접해 읽힌 날짜는
            // 한 묶음으로 배치해 전날의 마지막 행을 다음 날 사진이 채운다.
            // 아직 안 읽은 날짜는 별도 pending run으로 남아 지연 로딩한다.
            const laidOut = layoutBucket(
              `${g.key}-${runKey}`,
              items,
              width,
              tile,
            ).filter((r) => r.kind === "photos");
            const use =
              rowBudget === Infinity ? laidOut : laidOut.slice(0, rowBudget);
            for (const [i, r] of use.entries()) {
              if (r.kind !== "photos") continue;
              const rowItems = r.cells.map((c) => c.item);
              ordered.push(...rowItems);
              represented += rowItems.length;
              rows.push({
                kind: "photos",
                key: `p-${g.key}-${runKey}-${i}`,
                groupKey: g.key,
                day: run.days[0],
                items: rowItems,
                cells: r.cells,
                height: r.height,
              });
            }
            if (rowBudget !== Infinity) rowBudget -= use.length;
          } else {
            const cap = rowBudget === Infinity ? items.length : rowBudget * cols;
            const shown = items.slice(0, cap);
            const dayRows = Math.ceil(shown.length / cols);
            ordered.push(...shown);
            represented += shown.length;
            for (let i = 0; i < dayRows; i++) {
              rows.push({
                kind: "photos",
                key: `p-${g.key}-${runKey}-${i}`,
                groupKey: g.key,
                day: run.days[0],
                items: shown.slice(i * cols, i * cols + cols),
              });
            }
            if (rowBudget !== Infinity) rowBudget -= dayRows;
          }
          continue;
        }

        const day = run.day;
        const count = run.count;
        const estimatedRows = Math.max(1, Math.ceil(count / cols));
        const reserve =
          rowBudget === Infinity ? estimatedRows : Math.min(rowBudget, estimatedRows);
        represented += Math.min(count, reserve * cols);
        for (let i = 0; i < reserve; i++) {
          rows.push({
            kind: "placeholder",
            key: `x-${g.key}-${day}-${i}`,
            groupKey: g.key,
            day,
            cols,
          });
        }
        if (rowBudget !== Infinity) rowBudget -= reserve;
      }

      if (maxRows !== Infinity) {
        const hidden = Math.max(0, g.total - represented);
        if (hidden > 0) {
          rows.push({ kind: "more", key: `m-${g.key}`, groupKey: g.key, hidden });
        }
      }
    }
    return { rows, ordered };
  }, [groups, previewDaysOf, loaded, cols, maxRows, bucketCount, fit, width, tile]);

  useEffect(() => {
    setOrdered(ordered);
  }, [ordered, setOrdered]);

  // 스크롤·재측정 어느 쪽이든 위치가 바뀌면 tick — 안착 재확인과 크럼 갱신은
  // scroll 이벤트만으론 부족하다(위쪽 행이 실측되며 내용이 '조용히' 밀림).
  const [measureTick, setMeasureTick] = useState(0);
  const tickScheduled = useRef(false);
  const bumpTick = useCallback(() => {
    if (tickScheduled.current) return;
    tickScheduled.current = true;
    requestAnimationFrame(() => {
      tickScheduled.current = false;
      setMeasureTick((t) => t + 1);
    });
  }, []);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => {
      const r = rows[i];
      if (r?.kind === "header") return HEADER_H;
      if (r?.kind === "more") return 28;
      if (r?.kind === "photos" && r.height != null) return r.height;
      return tile + GAP;
    },
    // A row already contains several thumbnails. Large overscan multiplied
    // both day metadata calls and image requests on mobile; four rows are
    // enough for continuous month/day scrolling, and the dense year overview
    // needs only two.
    overscan: maxRows === Infinity ? 4 : 2,
    getItemKey: (i) => rows[i]?.key ?? i,
    onChange: bumpTick,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [rows, tile, virtualizer]);

  const virtualItems = virtualizer.getVirtualItems();

  // 화면(overscan 포함)에 실제로 들어온 placeholder의 날짜만 요청한다. 그룹
  // 하나가 보인다는 이유로 그 달 30일을 전부 요청하지 않는다.
  useEffect(() => {
    const have = new Set(requestedDays);
    const need = new Set<string>();
    for (const v of virtualItems) {
      const r = rows[v.index];
      if (r?.kind === "placeholder" && !have.has(r.day)) need.add(r.day);
    }
    if (need.size) setRequestedDays((prev) => [...prev, ...need]);
  });

  // scrollToGroup 대상 그룹의 미리보기 days를 선요청(화면 밖이라 placeholder
  // 요청 경로를 못 타는 경우 대비 — 로드돼야 높이가 실측되어 스크롤이 정확).
  useEffect(() => {
    if (!scrollToGroup) return;
    const g = groups.find((gr) => gr.key === scrollToGroup);
    if (!g) return;
    // 헤더 위치는 count 기반 placeholder만으로 계산 가능하다. 첫 날짜만 먼저
    // 읽고, 나머지는 스크롤 뷰포트가 접근할 때 위 경로로 점진 로드한다.
    const days = previewDaysOf(g).slice(0, 1);
    setRequestedDays((prev) => {
      const have = new Set(prev);
      const add = days.filter((d) => !have.has(d));
      return add.length ? [...prev, ...add] : prev;
    });
  }, [scrollToGroup, groups, previewDaysOf]);

  // scrollToGroup으로 초기 스크롤(연→월 드릴 등). 가상화 + 동적 높이라
  // placeholder 추정 위에서 한 번 스크롤하면 어긋남 → 대상 그룹이 로드돼
  // 높이가 실측될 때까지 rows/loaded 변화마다 재스크롤.
  // 연→월 드릴 안착: 독립 200ms 타이머로 대상 헤더를 상단에 재고정.
  // 위쪽 행들이 로드/실측되며 offset이 계속 밀리므로, "2회 연속 안정 + 대상
  // 그룹 로드됨"일 때까지 반복(휠/터치 개입 시 즉시 중단, 8초 상한).
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const loadedRef = useRef(loaded);
  loadedRef.current = loaded;
  const groupsRef = useRef(groups);
  groupsRef.current = groups;
  useEffect(() => {
    if (!scrollToGroup) return;
    const el = scrollRef.current;
    let stable = 0;
    let stopped = false;
    const stop = () => {
      stopped = true;
    };
    el?.addEventListener("wheel", stop, { passive: true });
    el?.addEventListener("touchstart", stop, { passive: true });
    const deadline = Date.now() + 8000;
    const timer = window.setInterval(() => {
      if (stopped || stable >= 2 || Date.now() > deadline) {
        window.clearInterval(timer);
        return;
      }
      const rs = rowsRef.current;
      const idx = rs.findIndex(
        (r) => r.kind === "header" && r.groupKey === scrollToGroup,
      );
      const box = scrollRef.current;
      if (idx < 0 || !box) return;
      // 대상 offset은 측정 캐시에서 직접 계산 — getVirtualItems()는 가상화기
      // 내부 offset이 스크롤을 못 따라간 동안(실측: scrollOffset 0 고정) 대상
      // 행을 아예 포함하지 않아 기준으로 쓸 수 없다.
      const target = virtualizer.getOffsetForIndex(idx, "start")?.[0];
      if (target == null) return;
      // 판정은 요소의 실제 scrollTop(진실) 기준.
      const g = groupsRef.current.find((gr) => gr.key === scrollToGroup);
      const firstDay = g ? previewDaysOf(g)[0] : null;
      const anchored = Math.abs(target - box.scrollTop) < 8;
      if (anchored && firstDay && loadedRef.current.has(firstDay)) {
        stable += 1;
        return; // 위치 유지 확인만(불필요한 재스크롤로 떨림 방지)
      }
      stable = 0;
      box.scrollTo({ top: target });
      // 가상화기 offset 구독이 프로그램 스크롤을 놓치는 경우가 있어(실측)
      // 명시적 scroll 이벤트로 동기화를 강제한다 — 없으면 렌더가 상단에 묶임.
      box.dispatchEvent(new Event("scroll"));
    }, 200);
    return () => {
      window.clearInterval(timer);
      el?.removeEventListener("wheel", stop);
      el?.removeEventListener("touchstart", stop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollToGroup, virtualizer]);

  // 뷰포트 최상단에 보이는 그룹 라벨 보고 — 상단 크럼이 실제 위치를 따라간다.
  useEffect(() => {
    if (!onTopGroupChange) return;
    const offset = scrollRef.current?.scrollTop ?? scrollTop;
    const vis = virtualizer.getVirtualItems();
    const top = vis.find((v) => v.end > offset + 1);
    const row = top ? rows[top.index] : null;
    onTopGroupChange(row ? labelOf(row.groupKey) : null);
  }, [scrollTop, measureTick, rows, virtualizer, onTopGroupChange, labelOf]);

  // 사이드 스크러버용 월 마커. 월/일 줌은 그룹 헤더의 실측 offset을 쓰고,
  // 연 줌은 한 해가 헤더 하나뿐이라 기존에는 연도당 마커 하나만 생겼다.
  // 연 그룹 안의 실제 보유 월을 그 해의 시각 영역에 균등 배치해 하위 기간
  // 눈금과 드래그 월 안내도 보이게 한다. 실제 스크롤 경계(연 헤더)는 유지한다.
  const totalSize = virtualizer.getTotalSize();
  const markers = useMemo<ScrubberMarker[]>(() => {
    const out: ScrubberMarker[] = [];
    const headers: { key: string; offset: number }[] = [];
    const groupsByKey = new Map(groups.map((g) => [g.key, g]));

    for (let i = 0; i < rows.length; i++) {
      const r = rows[i];
      if (r.kind !== "header") continue;
      const off = virtualizer.getOffsetForIndex(i, "start");
      const offset =
        typeof off === "number" ? off : Array.isArray(off) ? off[0] : 0;
      headers.push({ key: r.groupKey, offset });
    }

    let last = "";
    for (let i = 0; i < headers.length; i++) {
      const header = headers[i];
      const k = header.key;
      if (k.length <= 4) {
        const months = [
          ...new Set(
            (groupsByKey.get(k)?.days ?? []).map((day) => day.slice(0, 7)),
          ),
        ];
        if (months.length === 0) months.push(`${k}-01`);
        const end = headers[i + 1]?.offset ?? totalSize;
        const span = Math.max(0, end - header.offset);
        for (let j = 0; j < months.length; j++) {
          out.push({
            month: months[j],
            offset: header.offset + (span * j) / months.length,
          });
        }
        continue;
      }

      const month = k.slice(0, 7);
      if (month === last) continue;
      last = month;
      out.push({ month, offset: header.offset });
    }
    return out;
    // totalSize를 dep에 넣어 로드·측정으로 레이아웃이 바뀌면 재계산.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, groups, totalSize, viewportH]);

  if (groups.length === 0) {
    return (
      <p className="p-8 text-center text-sm text-slate-400">사진이 없습니다.</p>
    );
  }

  return (
    <div className="relative h-full">
      <div
        ref={setScrollRefs}
        className="h-full overflow-y-auto"
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
      {/* pl-3 pr-12: 우측 pr-12는 스크러버 레일 전용 거터(사진 없음). width
       * 측정 ref(contentEl)는 이 거터 안쪽 박스에 둬 열 수가 정확해진다. */}
      <div className="pl-3 pr-12">
      <div
        ref={setContentEl}
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
              {row.kind === "photos" &&
                (row.cells ? (
                  <div style={{ position: "relative", height: row.height }}>
                    {row.cells.map((c) => (
                      <button
                        key={c.item.id}
                        data-photo-id={c.item.id}
                        onClick={() => onPhotoClick(c.item)}
                        style={{
                          position: "absolute",
                          left: c.left,
                          top: 0,
                          width: c.width,
                          height: c.height,
                        }}
                        className="overflow-hidden rounded-sm focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-blue-400"
                      >
                        <Thumb item={c.item} space={space} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div style={{ display: "flex", gap: GAP }}>
                    {row.items.map((it) => (
                      <button
                        key={it.id}
                        data-photo-id={it.id}
                        onClick={() => onPhotoClick(it)}
                        style={{ width: tile, height: tile }}
                        className="overflow-hidden rounded-sm focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-blue-400"
                      >
                        <Thumb item={it} space={space} />
                      </button>
                    ))}
                  </div>
                ))}
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

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
import { boxesIntersect, useSelectionContainer } from "@air/react-drag-to-select";
import { api } from "../../api/client";
import type { PhotoItem } from "../../api/types";
import {
  buildRows,
  type BucketLayoutCacheEntry,
  type TimelineRowModel,
} from "../../lib/rowModel";
import { formatMonth } from "../../lib/dates";
import { useTimelineStore } from "../../store/timeline";
import { DateHeader } from "./DateHeader";
import { PhotoCell } from "./PhotoCell";
import { Scrubber, type ScrubberMarker } from "./Scrubber";

/** The timeline grid (spec 9.2, IMPROVEMENTS B-1/B-3/C):
 *
 * 1. Count-first: day buckets (counts only) arrive first; every unloaded day
 *    renders as fixed-height placeholders, so the scrollbar spans the whole
 *    archive immediately and the scrubber can map months to offsets.
 * 2. Row-level virtualization: the virtual unit is a justified row / header,
 *    never a single photo. Heights are known exactly from our own row model.
 * 3. Buckets lazily load as their rows approach the viewport; each bucket's
 *    justified geometry is computed once, per day — small and incremental.
 * 4. Box selection starts only on grid background (photo cells start DnD
 *    instead), keeping marquee and drag gestures conflict-free.
 */
export function TimelineView() {
  const space = useTimelineStore((s) => s.space);
  const setOrdered = useTimelineStore((s) => s.setOrdered);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollEl, setScrollEl] = useState<HTMLDivElement | null>(null);
  const setScrollRefs = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    setScrollEl(el);
  }, []);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  const [viewportH, setViewportH] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);

  // --- content width / viewport height ---
  useLayoutEffect(() => {
    const content = contentRef.current;
    const scroll = scrollRef.current;
    if (!content || !scroll) return;
    const ro = new ResizeObserver(() => {
      setWidth(Math.floor(content.clientWidth));
      setViewportH(scroll.clientHeight);
    });
    ro.observe(content);
    ro.observe(scroll);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = scrollEl;
    if (!el) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setScrollTop(el.scrollTop));
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("scroll", onScroll);
    };
  }, [scrollEl]);

  // --- data: buckets first (counts only), then per-day items on demand ---
  const bucketsQuery = useQuery({
    queryKey: ["buckets", space],
    queryFn: () => api.photoBuckets(space),
    staleTime: 5 * 60_000,
  });
  const buckets = useMemo(
    () => bucketsQuery.data?.buckets ?? [],
    [bucketsQuery.data],
  );

  const [requestedDays, setRequestedDays] = useState<string[]>([]);
  const itemQueries = useQueries({
    queries: requestedDays.map((day) => ({
      queryKey: ["bucket", space, day],
      queryFn: () => api.bucketItems(space, day),
      staleTime: Infinity,
    })),
  });
  // Signature keyed on which days have data — keeps loadedMap referentially
  // stable across unrelated re-renders (useQueries returns a fresh array).
  const loadedSig = itemQueries.map((q) => q.data?.day ?? "").join("|");
  const loadedMap = useMemo(() => {
    const m = new Map<string, PhotoItem[]>();
    for (const q of itemQueries) if (q.data) m.set(q.data.day, q.data.items);
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadedSig, space]);

  // --- row model (per-bucket geometry memoized in layoutCache) ---
  const layoutCacheRef = useRef(new Map<string, BucketLayoutCacheEntry>());
  const model = useMemo(
    () => buildRows(buckets, loadedMap, width, layoutCacheRef.current),
    [buckets, loadedMap, width],
  );

  useEffect(() => {
    setOrdered(model.orderedItems);
  }, [model.orderedItems, setOrdered]);

  const virtualizer = useVirtualizer({
    count: model.rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => model.rows[i]?.height ?? 0,
    overscan: 10,
    getItemKey: (i) => model.rows[i]?.key ?? i,
  });
  useEffect(() => {
    virtualizer.measure();
  }, [model.rows, virtualizer]);

  // --- scroll anchoring (Google Photos trick) ---
  // When buckets *above* the viewport load, their placeholder rows are
  // replaced by real geometry and everything below shifts. We anchor on the
  // day header of the first visible row (header keys survive the swap) and
  // compensate scrollTop by its offset delta before paint.
  const anchorRef = useRef<{ key: string; offset: number } | null>(null);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const anchor = anchorRef.current;
    if (!el || !anchor) return;
    const idx = model.rows.findIndex((r) => r.key === anchor.key);
    if (idx < 0) return;
    const delta = model.offsets[idx] - anchor.offset;
    if (Math.abs(delta) > 1) {
      el.scrollTop += delta;
      anchorRef.current = { key: anchor.key, offset: model.offsets[idx] };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model]);

  const virtualItems = virtualizer.getVirtualItems();

  // Track the anchor after adjustments (useEffect runs after useLayoutEffect).
  useEffect(() => {
    const first = virtualItems[0];
    if (!first) return;
    const row = model.rows[first.index];
    if (!row) return;
    const headerKey = `h-${row.day}`;
    const headerIdx = model.rows.findIndex((r) => r.key === headerKey);
    if (headerIdx >= 0) {
      anchorRef.current = { key: headerKey, offset: model.offsets[headerIdx] };
    }
  });

  // Request buckets whose rows entered the (overscanned) viewport.
  useEffect(() => {
    const have = new Set(requestedDays);
    const need: string[] = [];
    for (const v of virtualItems) {
      const row = model.rows[v.index];
      if (row && !have.has(row.day) && !need.includes(row.day)) need.push(row.day);
    }
    if (need.length) setRequestedDays((prev) => [...prev, ...need]);
  });

  // --- marquee (box) selection: background drag only ---
  const baseSelectionRef = useRef<ReadonlySet<string>>(new Set());
  const { DragSelection } = useSelectionContainer({
    eventsElement: scrollEl,
    shouldStartSelecting: (target) => {
      if (!(target instanceof Element)) return false;
      return (
        !target.closest("[data-photo-id]") && !target.closest("[data-no-boxselect]")
      );
    },
    onSelectionStart: (e) => {
      const s = useTimelineStore.getState();
      baseSelectionRef.current = e.shiftKey ? new Set(s.selected) : new Set();
    },
    onSelectionChange: (box) => {
      const container = scrollRef.current;
      if (!container) return;
      const ids = new Set(baseSelectionRef.current);
      // Only mounted (≈visible) cells participate — coordinate math stays
      // cheap and correct under virtualization.
      container.querySelectorAll<HTMLElement>("[data-photo-id]").forEach((el) => {
        const r = el.getBoundingClientRect();
        if (
          boxesIntersect(box, {
            left: r.left,
            top: r.top,
            width: r.width,
            height: r.height,
          })
        ) {
          const id = el.dataset.photoId;
          if (id) ids.add(id);
        }
      });
      useTimelineStore.getState().replaceSelection([...ids]);
    },
    selectionProps: {
      style: {
        border: "1px solid rgba(59,130,246,0.8)",
        background: "rgba(59,130,246,0.12)",
        borderRadius: 2,
        zIndex: 30,
      },
    },
  });

  // --- scrubber markers: first offset of each month ---
  const markers = useMemo<ScrubberMarker[]>(() => {
    const out: ScrubberMarker[] = [];
    let lastMonth = "";
    model.rows.forEach((row, i) => {
      if (row.kind !== "header") return;
      const month = row.day.slice(0, 7);
      if (month !== lastMonth) {
        lastMonth = month;
        out.push({ month, offset: model.offsets[i] });
      }
    });
    return out;
  }, [model]);

  // Floating date pill: month of the first visible row.
  const pillLabel = useMemo(() => {
    if (model.rows.length === 0) return null;
    let lo = 0;
    let hi = model.rows.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (model.offsets[mid] + model.rows[mid].height <= scrollTop) lo = mid + 1;
      else hi = mid;
    }
    const day = model.rows[lo]?.day;
    return day ? formatMonth(day) : null;
  }, [model, scrollTop]);

  if (bucketsQuery.isPending) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        타임라인 불러오는 중…
      </div>
    );
  }
  if (bucketsQuery.isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-500">
        <p>타임라인을 불러오지 못했습니다.</p>
        <button
          onClick={() => bucketsQuery.refetch()}
          className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50"
        >
          다시 시도
        </button>
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
    <div ref={setScrollRefs} className="relative h-full overflow-y-auto">
      <DragSelection />
      {pillLabel && (
        // h-0 wrapper: the pill floats over the grid without occupying layout
        // space (which would shift every virtualized row's offset).
        <div className="pointer-events-none sticky top-0 z-20 h-0">
          <span className="ml-3 mt-2 inline-block rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-white shadow">
            {pillLabel}
          </span>
        </div>
      )}
      <div ref={contentRef} className="px-3">
        <div
          style={{
            height: virtualizer.getTotalSize(),
            width: "100%",
            position: "relative",
          }}
        >
          {virtualItems.map((v) => {
            const row = model.rows[v.index];
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
                <RowRenderer row={row} items={loadedMap.get(row.day)} />
              </div>
            );
          })}
        </div>
      </div>
      <Scrubber
        markers={markers}
        totalHeight={model.totalHeight}
        viewportHeight={viewportH}
        scrollTop={scrollTop}
        onJump={(offset) => virtualizer.scrollToOffset(offset)}
      />
    </div>
  );
}

function RowRenderer({
  row,
  items,
}: {
  row: TimelineRowModel;
  items?: PhotoItem[];
}) {
  if (row.kind === "header") {
    return <DateHeader day={row.day} items={items} />;
  }
  if (row.kind === "photos") {
    return (
      <div style={{ position: "relative", height: row.height }}>
        {row.cells.map((cell) => (
          <PhotoCell key={cell.item.id} cell={cell} />
        ))}
      </div>
    );
  }
  // Unloaded bucket: neutral placeholder boxes sized like a real row.
  return (
    <div className="flex gap-2" style={{ height: row.height, paddingBottom: 8 }}>
      {Array.from({ length: row.cols }, (_, i) => (
        <div key={i} className="h-full flex-1 rounded-sm bg-slate-200/80" />
      ))}
    </div>
  );
}

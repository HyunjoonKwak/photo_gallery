/** Timeline row model: turns (buckets, loaded items, width) into virtual rows.
 *
 * Count-first design (docs/IMPROVEMENTS.md B-1): buckets give day+count only,
 * so unloaded days become fixed-height placeholder rows — the scrollbar
 * represents the whole archive before any item loads. Loaded days are laid out
 * with flickr/justified-layout. Geometry is computed **per day bucket** and
 * memoized in `cache`, so work stays small and incremental (the Immich #28861
 * synchronous-geometry freeze is avoided by construction: day buckets are
 * small, and only newly loaded buckets compute).
 */

import justifiedLayout from "justified-layout";
import type { PhotoBucket, PhotoItem } from "../api/types";

export const TARGET_ROW_H = 176;
export const GAP = 8;
export const HEADER_H = 48;
/** Average aspect ratio used to estimate rows for unloaded buckets. */
const EST_ASPECT = 1.35;

export interface CellLayout {
  item: PhotoItem;
  left: number;
  width: number;
  height: number;
}

export type TimelineRowModel =
  | { kind: "header"; key: string; day: string; height: number }
  | { kind: "photos"; key: string; day: string; cells: CellLayout[]; height: number }
  | { kind: "placeholder"; key: string; day: string; cols: number; height: number };

export interface RowModelResult {
  rows: TimelineRowModel[];
  /** Loaded items in display order (drives shift-range + lightbox stepping). */
  orderedItems: PhotoItem[];
  /** Start offset of each row (prefix sums of heights). */
  offsets: number[];
  totalHeight: number;
}

export interface BucketLayoutCacheEntry {
  width: number;
  count: number;
  rows: TimelineRowModel[];
}

/** Justified rows for one item list (a day bucket, or a folder's contents). */
export function layoutBucket(
  day: string,
  items: PhotoItem[],
  containerWidth: number,
): TimelineRowModel[] {
  const geometry = justifiedLayout(
    items.map((i) => ({ width: i.width || 4, height: i.height || 3 })),
    {
      containerWidth,
      containerPadding: 0,
      boxSpacing: GAP,
      targetRowHeight: TARGET_ROW_H,
    },
  );

  const rows: TimelineRowModel[] = [];
  let currentTop = -1;
  geometry.boxes.forEach((box, i) => {
    if (box.top !== currentTop) {
      currentTop = box.top;
      rows.push({
        kind: "photos",
        key: `p-${day}-${rows.length}`,
        day,
        cells: [],
        height: Math.round(box.height) + GAP,
      });
    }
    const row = rows[rows.length - 1];
    if (row.kind === "photos") {
      row.cells.push({
        item: items[i],
        left: box.left,
        width: box.width,
        height: box.height,
      });
    }
  });
  return rows;
}

/** Estimated placeholder rows for an unloaded bucket (count-first). */
function placeholderRows(day: string, count: number, width: number): TimelineRowModel[] {
  const perRow = Math.max(1, Math.round(width / (TARGET_ROW_H * EST_ASPECT + GAP)));
  const nRows = Math.ceil(count / perRow);
  const rows: TimelineRowModel[] = [];
  for (let r = 0; r < nRows; r++) {
    rows.push({
      kind: "placeholder",
      key: `ph-${day}-${r}`,
      day,
      cols: Math.min(perRow, count - r * perRow),
      height: TARGET_ROW_H + GAP,
    });
  }
  return rows;
}

export function buildRows(
  buckets: PhotoBucket[],
  loaded: Map<string, PhotoItem[]>,
  width: number,
  cache: Map<string, BucketLayoutCacheEntry>,
): RowModelResult {
  const rows: TimelineRowModel[] = [];
  const orderedItems: PhotoItem[] = [];

  if (width > 0) {
    for (const bucket of buckets) {
      rows.push({
        kind: "header",
        key: `h-${bucket.day}`,
        day: bucket.day,
        height: HEADER_H,
      });
      const items = loaded.get(bucket.day);
      if (items) {
        let entry = cache.get(bucket.day);
        if (!entry || entry.width !== width || entry.count !== items.length) {
          entry = { width, count: items.length, rows: layoutBucket(bucket.day, items, width) };
          cache.set(bucket.day, entry);
        }
        rows.push(...entry.rows);
        orderedItems.push(...items);
      } else {
        rows.push(...placeholderRows(bucket.day, bucket.count, width));
      }
    }
  }

  const offsets: number[] = new Array(rows.length);
  let acc = 0;
  rows.forEach((row, i) => {
    offsets[i] = acc;
    acc += row.height;
  });

  return { rows, orderedItems, offsets, totalHeight: acc };
}

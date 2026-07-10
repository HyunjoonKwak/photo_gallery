/** Justified row layout for one item list (a day bucket, a folder's contents,
 * or search results). Geometry is computed per list with flickr/justified-
 * layout; rows are fixed-height so grids can virtualize by row (VirtualRows).
 * (구 count-first 타임라인의 buildRows/placeholderRows는 IA 개편으로 미사용이
 * 되어 제거 — Phase C 죽은 코드 정리, 2026-07-10.)
 */

import justifiedLayout from "justified-layout";
import type { PhotoItem } from "../api/types";

export const TARGET_ROW_H = 176;
export const GAP = 8;

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

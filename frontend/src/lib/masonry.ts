import type { PhotoItem } from "../api/types";

export interface MasonryCell {
  item: PhotoItem;
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface MasonryLayout {
  cells: MasonryCell[];
  /** 가장 긴 열의 높이 — 스크롤 상자가 잡아야 할 전체 높이 */
  height: number;
  /** 띠별로 그 안에 걸치는 셀의 인덱스. 스크롤 위치로 O(1) 조회한다. */
  bands: number[][];
}

/**
 * 띠 하나의 높이 (px). 화면 하나보다 넉넉해야 스크롤 중 빈칸이 안 생기고,
 * 너무 크면 한 번에 그리는 셀이 늘어난다.
 */
export const BAND_H = 600;

/**
 * 메이슨리 배치 — 열 폭은 같고 높이는 사진 비율대로.
 *
 * 정사각 그리드는 세로 사진의 위아래를 잘라 낸다. 인물 사진이 많은 가족
 * 앨범에서는 얼굴이 잘리는 일이 잦다. 여기서는 자르지 않는다.
 *
 * **행이 없어서** 타임라인처럼 «몇 번째 행»으로 가상화할 수 없다. 대신 배치
 * 결과를 고정 높이의 띠로 색인해 둔다 — 스크롤 위치를 띠 번호로 나누면
 * 그릴 셀이 바로 나온다(전체를 훑지 않는다).
 */
export function layoutMasonry(
  items: PhotoItem[],
  containerWidth: number,
  minColumn: number,
  gap: number,
): MasonryLayout {
  if (containerWidth <= 0 || items.length === 0)
    return { cells: [], height: 0, bands: [] };

  const cols = Math.max(
    1,
    Math.floor((containerWidth + gap) / (minColumn + gap)),
  );
  const colW = (containerWidth - gap * (cols - 1)) / cols;
  const colTops = new Array<number>(cols).fill(0);

  const cells: MasonryCell[] = [];
  const bands: number[][] = [];

  for (const item of items) {
    // 치수가 비어 오는 항목이 있다(스캔 전). 4:3 으로 가정 — rowModel 과 같다.
    const w = item.width || 4;
    const h = item.height || 3;
    const cellH = Math.round(colW * (h / w));

    // 가장 짧은 열에 넣는다. 열이 몇 개 안 되므로 훑는 편이 빠르다.
    let col = 0;
    for (let c = 1; c < cols; c++) if (colTops[c] < colTops[col]) col = c;

    const top = colTops[col];
    const index = cells.length;
    cells.push({
      item,
      left: col * (colW + gap),
      top,
      width: colW,
      height: cellH,
    });
    colTops[col] = top + cellH + gap;

    const first = Math.floor(top / BAND_H);
    const last = Math.floor((top + cellH) / BAND_H);
    for (let b = first; b <= last; b++) {
      (bands[b] ??= []).push(index);
    }
  }

  const height = Math.max(...colTops) - gap;
  // 중간에 빈 띠가 생길 수는 없지만(셀이 이어 붙는다) 배열 구멍은 막아 둔다.
  for (let b = 0; b < bands.length; b++) bands[b] ??= [];

  return { cells, height: Math.max(0, height), bands };
}

/** 보이는 구간에 걸치는 셀 인덱스. 띠 경계에 걸친 셀은 한 번만 준다. */
export function visibleCells(
  layout: MasonryLayout,
  scrollTop: number,
  viewportH: number,
  overscanPx = BAND_H,
): number[] {
  if (layout.bands.length === 0) return [];
  const from = Math.max(0, Math.floor((scrollTop - overscanPx) / BAND_H));
  const to = Math.min(
    layout.bands.length - 1,
    Math.floor((scrollTop + viewportH + overscanPx) / BAND_H),
  );
  const seen = new Set<number>();
  for (let b = from; b <= to; b++) {
    for (const i of layout.bands[b]) seen.add(i);
  }
  return [...seen];
}

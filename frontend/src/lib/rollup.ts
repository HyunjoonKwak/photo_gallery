import type { PhotoBucket } from "../api/types";

/** 사진 뷰어 연/월 집계 결과 (프론트 롤업 — 별도 API 없이 buckets 재사용). */
export interface RollupGroup {
  key: string; // "2024" (연) | "2024-03" (월)
  count: number; // 그룹 내 총 사진 수
  coverDay: string; // 대표(최신) day — 커버 썸네일 조회에 사용
}

function rollup(
  buckets: PhotoBucket[],
  keyOf: (day: string) => string,
  filter?: (day: string) => boolean,
): RollupGroup[] {
  const map = new Map<string, { count: number; coverDay: string }>();
  for (const b of buckets) {
    if (filter && !filter(b.day)) continue;
    const key = keyOf(b.day);
    const e = map.get(key);
    if (e) {
      e.count += b.count;
      if (b.day > e.coverDay) e.coverDay = b.day; // ISO 문자열 비교 = 날짜 비교
    } else {
      map.set(key, { count: b.count, coverDay: b.day });
    }
  }
  // 최신 그룹이 위로 (연/월 뷰는 최근부터).
  return [...map.entries()]
    .map(([key, v]) => ({ key, count: v.count, coverDay: v.coverDay }))
    .sort((a, b) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0));
}

/** 연도별 집계 ("2024" …). */
export function rollupYears(buckets: PhotoBucket[]): RollupGroup[] {
  return rollup(buckets, (d) => d.slice(0, 4));
}

/** 월별 집계 ("2024-03" …). year 지정 시 그 해만. */
export function rollupMonths(
  buckets: PhotoBucket[],
  year?: string,
): RollupGroup[] {
  return rollup(
    buckets,
    (d) => d.slice(0, 7),
    year ? (d) => d.slice(0, 4) === year : undefined,
  );
}

/** 한 해/한 달 라벨 (한국어). */
export function yearLabel(key: string): string {
  return `${key}년`;
}
export function monthLabel(key: string): string {
  const [y, m] = key.split("-");
  return `${y}년 ${Number(m)}월`;
}

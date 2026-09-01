import type { PhotoItem } from "../api/types";
import type { ScrubberMarker } from "../components/timeline/Scrubber";

/**
 * 목록이 달 순서로 늘어서 있는가.
 *
 * 스크러버는 "레일의 위아래가 곧 시간"이라는 약속 위에 서 있다. 앨범처럼
 * 사람이 정한 순서에 그 레일을 달면 연·월 라벨이 뒤죽박죽 섞여 **거짓말을
 * 한다** — 2019가 2024 아래에 오고, 끌어도 엉뚱한 데로 간다.
 * 그래서 레일을 달기 전에 목록 자체에 물어본다.
 *
 * **달까지만 본다.** 레일에 찍히는 것이 연·월뿐이라 그 아래 순서는 레일의
 * 정확성과 무관하고, 실제 목록은 같은 날 안에서 시각이 뒤섞여 온다
 * (실측: `08:32 → 17:05 → 14:18`). 초 단위로 따지면 멀쩡한 시간순 목록이
 * 전부 탈락한다.
 *
 * 오름차순·내림차순을 가리지 않는다(둘 다 시간순이다).
 */
export function isMonthOrdered(items: PhotoItem[]): boolean {
  let dir = 0;
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1].taken_at.slice(0, 7);
    const cur = items[i].taken_at.slice(0, 7);
    if (prev === cur) continue;
    const step = prev < cur ? 1 : -1;
    if (dir === 0) dir = step;
    else if (step !== dir) return false;
  }
  return dir !== 0;
}

/**
 * 균일 행 그리드(정사각 타일)의 월 마커.
 *
 * 행 높이가 일정해서 «몇 번째 사진인가»만 알면 픽셀 위치가 바로 나온다.
 * 날짜 헤더가 끼는 타임라인 그리드는 가상화기에게 실측을 물어야 하지만
 * (`DateGroupedGrid`), 여기서는 곱셈 한 번이면 된다.
 */
export function uniformMonthMarkers(
  items: PhotoItem[],
  cols: number,
  rowHeight: number,
): ScrubberMarker[] {
  if (cols <= 0 || rowHeight <= 0) return [];
  const out: ScrubberMarker[] = [];
  let last = "";
  for (let i = 0; i < items.length; i++) {
    const month = items[i].taken_at.slice(0, 7);
    if (month === last) continue;
    last = month;
    out.push({ month, offset: Math.floor(i / cols) * rowHeight });
  }
  return out;
}

import { useTimelineStore } from "../../store/timeline";

/**
 * 사진 배치 전환 — 정사각(잘라 채움) ↔ 비율(원본 그대로).
 *
 * 처음엔 그리드 좌상단에 떠 있게 뒀는데, 정작 가장 많이 보는 「사진」 탭
 * (타임라인)에는 그 그리드가 없어 기능을 만날 수조차 없었다(2026-09-01
 * 사용자 제보). 렌즈 바·앨범 머리줄처럼 **늘 같은 자리**로 옮긴다.
 *
 * 고른 값은 기기에 남아(localStorage) 화면을 옮겨도 따라온다. 화면마다
 * «비율»의 구현은 다르다 — 타임라인은 justified(행 유지), 앨범·렌즈는
 * 메이슨리(열 기반). 보는 사람에게는 «안 잘린다»는 같은 약속이다.
 */
export function PhotoLayoutToggle({ className = "" }: { className?: string }) {
  const layout = useTimelineStore((s) => s.photoLayout);
  const setLayout = useTimelineStore((s) => s.setPhotoLayout);
  const masonry = layout === "masonry";
  return (
    <button
      data-no-boxselect
      onClick={() => setLayout(masonry ? "square" : "masonry")}
      title={
        masonry
          ? "정사각으로 보기 — 칸이 고르게 맞습니다"
          : "비율 그대로 보기 — 세로 사진이 잘리지 않습니다"
      }
      aria-pressed={masonry}
      className={`flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition-colors ${
        masonry
          ? "bg-slate-800 text-white"
          : "text-slate-500 hover:bg-slate-100 hover:text-slate-700"
      } ${className}`}
    >
      <span aria-hidden>{masonry ? "▥" : "▦"}</span>
      {masonry ? "비율" : "정사각"}
    </button>
  );
}

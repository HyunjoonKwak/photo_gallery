import { useEffect, useState } from "react";
import { selectBackDepth, useTimelineStore } from "../store/timeline";

/** 화면 탐색 편의: 뒤로/최상단 버튼을 띄운다. 뒤로가기 트랩 자체는
 * useBackTrap(App 최상위, 로그인 게이팅 무관)이 담당한다. */
export function NavControls() {
  // canGoBack을 반응형으로: 뒤로 깊이 셀렉터를 직접 구독(단일 소스).
  const backDepth = useTimelineStore(selectBackDepth);
  const canBack = backDepth > 0;
  const section = useTimelineStore((s) => s.section);
  // 우측 날짜 스크러버(연/월 라벨 레일)가 떠 있으면 레일(w-10) 왼쪽으로
  // 비켜난다 — 연도 라벨·버튼 겹침 방지.
  const scrubberVisible = useTimelineStore((s) => s.scrubberCount > 0);

  // --- 최상단 버튼: 내부 스크롤 컨테이너가 내려가 있으면 노출 ---
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = (e: Event) => {
      const t = e.target as HTMLElement | null;
      if (t?.classList?.contains("overflow-y-auto")) {
        setScrolled(t.scrollTop > 400);
      }
    };
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, []);
  // 다른 탭·드릴 단계로 바뀌면 이전 스크롤 컨테이너의 상태를 버린다.
  // 그렇지 않으면 새 화면이 맨 위인데도 최상단 버튼이 남아 보인다.
  useEffect(() => setScrolled(false), [section, backDepth]);
  const scrollToTop = () => {
    const els = [
      ...document.querySelectorAll<HTMLElement>(".overflow-y-auto"),
    ].sort((a, b) => b.scrollTop - a.scrollTop);
    els[0]?.scrollTo({ top: 0, behavior: "smooth" });
    setScrolled(false);
  };

  const btn =
    "flex h-10 w-10 items-center justify-center rounded-full bg-white/95 text-lg text-slate-600 shadow-md ring-1 ring-slate-200 backdrop-blur active:scale-95 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500";

  if (!scrolled && !canBack) return null;

  return (
    <div
      data-no-boxselect
      className={`fixed z-20 flex flex-col items-center gap-2 bottom-[calc(env(safe-area-inset-bottom)+4.75rem)] transition-[right] duration-200 md:bottom-5 ${
        scrubberVisible ? "right-12" : "right-3"
      }`}
    >
      {scrolled && (
        <button
          className={btn}
          title="최상단으로"
          aria-label="최상단으로"
          onClick={scrollToTop}
        >
          ↑
        </button>
      )}
      {canBack && (
        <button
          className={btn}
          title="뒤로"
          aria-label="뒤로"
          onClick={() => history.back()}
        >
          ‹
        </button>
      )}
    </div>
  );
}

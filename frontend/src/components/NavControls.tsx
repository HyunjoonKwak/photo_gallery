import { useEffect, useState } from "react";
import { useTimelineStore } from "../store/timeline";

/** 화면 탐색 편의: 브라우저 뒤로가기를 앱 내 "뒤로"로 연결(트랩)하고,
 * 화면에 뒤로/홈/최상단 버튼을 띄운다. 상태 기반 SPA라 URL 히스토리가 없어
 * 모바일 뒤로가기가 사이트를 나가버리던 문제를 해결한다. */
export function NavControls() {
  const goHome = useTimelineStore((s) => s.goHome);
  // canGoBack을 반응형으로: 관련 상태를 직접 구독.
  const canBack = useTimelineStore((s) =>
    Boolean(
      s.lightboxId ||
        s._backHandlers.length ||
        s.groupId ||
        (s.section === "viewer" && s.zoom !== "year") ||
        s.section !== "viewer",
    ),
  );

  // --- 브라우저 뒤로가기 트랩 ---
  // 뒤로 갈 곳이 있으면 히스토리에 센티넬 1개를 유지하고, 뒤로가기(popstate)를
  // 앱 내 goBack으로 소비한다. 최상위에선 센티넬을 두지 않아 정상 이탈된다.
  useEffect(() => {
    let armed = false;
    const arm = () => {
      if (!armed && useTimelineStore.getState().canGoBack()) {
        history.pushState({ __nav: true }, "");
        armed = true;
      }
    };
    const onPop = () => {
      armed = false; // 센티넬이 소비됨
      if (useTimelineStore.getState().goBack()) arm(); // 처리했고 더 깊으면 재장전
      // 최상위면 재장전하지 않음 → 다음 뒤로가기는 사이트 이탈
    };
    window.addEventListener("popstate", onPop);
    const unsub = useTimelineStore.subscribe(arm); // 드릴인 시 자동 장전
    arm();
    return () => {
      window.removeEventListener("popstate", onPop);
      unsub();
    };
  }, []);

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
  const scrollToTop = () => {
    const els = [
      ...document.querySelectorAll<HTMLElement>(".overflow-y-auto"),
    ].sort((a, b) => b.scrollTop - a.scrollTop);
    els[0]?.scrollTo({ top: 0, behavior: "smooth" });
    setScrolled(false);
  };

  const btn =
    "flex h-10 w-10 items-center justify-center rounded-full bg-white/95 text-lg text-slate-600 shadow-md ring-1 ring-slate-200 backdrop-blur active:scale-95 hover:bg-white";

  return (
    <div
      data-no-boxselect
      className="fixed right-3 z-20 flex flex-col items-center gap-2 bottom-[calc(env(safe-area-inset-bottom)+4.75rem)] md:bottom-5"
    >
      {scrolled && (
        <button className={btn} title="최상단으로" onClick={scrollToTop}>
          ↑
        </button>
      )}
      {canBack && (
        <button
          className={btn}
          title="뒤로"
          onClick={() => history.back()}
        >
          ‹
        </button>
      )}
      <button className={btn} title="홈(사진)" onClick={() => goHome()}>
        🏠
      </button>
    </div>
  );
}

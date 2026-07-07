import { useEffect, useState } from "react";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";

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
        s._navHistory.length,
    ),
  );

  // --- 브라우저 뒤로가기 트랩 + 종료 확인 ---
  // 히스토리에 센티넬 1개를 항상 유지해 뒤로가기(popstate)를 가로챈다.
  // 화면 내에서 되돌릴 게 있으면 goBack으로 한 단계 되돌리고, 최상위에선
  // 곧바로 나가지 않고 "한 번 더 누르면 종료" 안내 → 2.5초 내 재차 뒤로가기면
  // 실제로 이탈(이전 페이지로/설치앱 종료).
  //
  // 모바일 PWA 견고성:
  // - 센티넬 유무를 클로저 플래그가 아니라 history.state로 판정한다. 앱을
  //   백그라운드→재개(bfcache)하면 클로저 플래그가 실제 스택과 어긋나
  //   최상위 확인이 통째로 건너뛰어지던 문제를 없앤다.
  // - 일부 모바일 브라우저는 popstate 핸들러 안에서 동기적으로 부른
  //   pushState(센티넬 재장전)를 무시한다 → 다음 틱에 한 번 더 보강한다.
  // - pageshow/visibilitychange(재개)에도 센티넬을 재장전한다.
  useEffect(() => {
    let lastRootBack = 0;
    let exiting = false;
    const onSentinel = () =>
      Boolean((history.state as { __nav?: boolean } | null)?.__nav);
    const armNow = () => {
      if (!exiting && !onSentinel()) history.pushState({ __nav: true }, "");
    };
    // 동기 pushState가 무시되는 브라우저 대비: 다음 틱에도 센티넬을 보장.
    const arm = () => {
      armNow();
      window.setTimeout(armNow, 0);
    };
    const onPop = () => {
      if (exiting) return;
      if (useTimelineStore.getState().goBack()) {
        arm(); // 화면 내 한 단계 되돌림 → 재장전
        return;
      }
      // 최상위: 종료 확인
      const now = Date.now();
      if (now - lastRootBack < 2500) {
        exiting = true; // 확인됨 → 실제 이탈
        window.removeEventListener("popstate", onPop);
        history.back();
        return;
      }
      lastRootBack = now;
      useToastStore.getState().push("한 번 더 뒤로가기를 누르면 종료됩니다");
      arm(); // 머무름 — 센티넬 재장전
    };
    const onResume = () => armNow();
    window.addEventListener("popstate", onPop);
    window.addEventListener("pageshow", onResume);
    document.addEventListener("visibilitychange", onResume);
    armNow(); // 로드 시 센티넬 1개 장전
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("pageshow", onResume);
      document.removeEventListener("visibilitychange", onResume);
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

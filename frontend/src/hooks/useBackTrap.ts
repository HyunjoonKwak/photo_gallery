import { useEffect } from "react";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";

/** 브라우저/시스템 뒤로가기 트랩 + 최상위 종료 확인.
 *
 * 앱 최상위(더 되돌릴 게 없는 상태)에서 뒤로가기를 누르면 곧바로 나가지 않고
 * "한 번 더 누르면 종료" 토스트를 띄우고, 2.5초 안에 재차 뒤로가기면 실제로
 * 이탈한다. 상태 기반 SPA라 URL 히스토리가 없어, 히스토리에 센티넬 1개를
 * 항상 유지해 뒤로가기(popstate)를 가로챈다.
 *
 * 중요: 이 트랩은 **로그인/세션 확인 게이팅과 무관하게 앱 마운트 즉시** 걸려야
 * 한다. 로그인 화면·"세션 확인 중"에서 뒤로가기를 눌러도 곧장 앱이 종료되던
 * 문제(NavControls가 로그인 후에만 마운트되던 타이밍 구멍)를 막는다. 그래서
 * 센티넬은 모듈 로드 시점(main.tsx)에 미리 깔고, 이 훅은 App 최상위에서
 * 어떤 조기 반환보다 먼저 호출한다.
 *
 * 모바일 PWA 견고성:
 * - 센티넬 유무를 클로저 플래그가 아니라 history.state로 판정(재개/재로딩 후
 *   실제 스택과 어긋나지 않게).
 * - 일부 브라우저가 popstate 핸들러 내 동기 pushState를 무시 → 다음 틱 보강.
 * - pageshow/visibilitychange(재개)에도 센티넬 재장전.
 */
export function useBackTrap(): void {
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
    armNow(); // 마운트 시 센티넬 보장(main.tsx에서 이미 깔았어도 멱등)
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("pageshow", onResume);
      document.removeEventListener("visibilitychange", onResume);
    };
  }, []);
}

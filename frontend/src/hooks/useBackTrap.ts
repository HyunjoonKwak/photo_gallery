import { useEffect } from "react";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";

/** 뒤로가기 트랩 진단 로그 — 앱이 닫혀도 남도록 localStorage에 최근 이벤트를
 * 기록한다. BuildBadge(헤더 표식 탭)가 읽어 실기기에서 popstate 발화 여부·
 * 순서를 눈으로 확인하게 한다. */
const DBG_KEY = "nav.dbg";
export function navDbg(msg: string): void {
  try {
    const t = new Date().toISOString().slice(14, 19); // mm:ss
    const arr = JSON.parse(localStorage.getItem(DBG_KEY) || "[]") as string[];
    arr.push(`${t} ${msg}`);
    localStorage.setItem(DBG_KEY, JSON.stringify(arr.slice(-14)));
  } catch {
    // storage 접근 불가(사생활 모드 등) — 진단만 생략.
  }
}

/** 브라우저/시스템 뒤로가기 트랩 + 최상위 종료 확인.
 *
 * 앱 최상위(더 되돌릴 게 없는 상태)에서 뒤로가기를 누르면 곧바로 나가지 않고
 * "한 번 더 누르면 종료" 토스트를 띄우고, 2.5초 안에 재차 뒤로가기면 실제로
 * 이탈한다. 상태 기반 SPA라 URL 히스토리가 없어, 히스토리에 센티넬 1개를
 * 항상 유지해 뒤로가기(popstate)를 가로챈다.
 *
 * 핵심(모바일 Chrome): Chrome은 **사용자 제스처 없이 pushState로 만든
 * 히스토리 항목을 뒤로가기 때 건너뛴다**("history manipulation intervention",
 * pushState 남용 방지). 그래서 센티넬을 로드 시점에 깔면 안드로이드 설치앱에서
 * 뒤로가기가 센티넬을 건너뛰고 곧장 앱을 종료(popstate 미발화)한다. 반드시
 * **첫 사용자 상호작용(sticky activation) 이후**에 센티넬을 깐다. 그 뒤로는
 * 페이지에 sticky activation이 생겨 이후 pushState는 건너뛰기 대상이 아니고,
 * popstate 재장전(뒤로가기 제스처 자체가 사용자 활성)도 정상 항목이 된다.
 *
 * 모바일 PWA 견고성:
 * - 센티넬 유무를 클로저 플래그가 아니라 history.state로 판정(재개/재로딩 후
 *   실제 스택과 어긋나지 않게).
 * - 일부 브라우저가 popstate 핸들러 내 동기 pushState를 무시 → 다음 틱 보강.
 * - pageshow/visibilitychange(재개)에도 센티넬 재장전(단, 최초 제스처 이후).
 */
export function useBackTrap(): void {
  useEffect(() => {
    let lastRootBack = 0;
    let exiting = false;
    let activated = false; // 사용자 상호작용이 한 번이라도 있었나
    navDbg(`load std=${window.matchMedia("(display-mode: standalone)").matches}`);
    const onSentinel = () =>
      Boolean((history.state as { __nav?: boolean } | null)?.__nav);
    const armNow = () => {
      if (!exiting && activated && !onSentinel()) {
        history.pushState({ __nav: true }, "");
      }
    };
    // 동기 pushState가 무시되는 브라우저 대비: 다음 틱에도 센티넬을 보장.
    const arm = () => {
      armNow();
      window.setTimeout(armNow, 0);
    };
    const onPop = () => {
      if (exiting) return;
      const back = useTimelineStore.getState().goBack();
      navDbg(`pop goBack=${back} sent=${onSentinel()} hlen=${history.length}`);
      if (back) {
        arm(); // 화면 내 한 단계 되돌림 → 재장전
        return;
      }
      // 최상위: 종료 확인
      const now = Date.now();
      if (now - lastRootBack < 2500) {
        exiting = true; // 확인됨 → 실제 이탈
        navDbg("exit");
        window.removeEventListener("popstate", onPop);
        history.back();
        return;
      }
      lastRootBack = now;
      navDbg("toast");
      useToastStore.getState().push("한 번 더 뒤로가기를 누르면 종료됩니다");
      arm(); // 머무름 — 센티넬 재장전
    };
    // 첫 사용자 제스처에 센티넬 장전(그 전엔 Chrome이 건너뛰어 무용지물).
    // 이후 상호작용마다 확인(멱등) — 센티넬이 소비된 상태면 다시 채운다.
    const onGesture = () => {
      const first = !activated;
      activated = true;
      armNow();
      if (first) navDbg(`act sent=${onSentinel()} hlen=${history.length}`);
    };
    const onResume = () => armNow();
    window.addEventListener("popstate", onPop);
    window.addEventListener("pointerdown", onGesture);
    window.addEventListener("keydown", onGesture);
    window.addEventListener("pageshow", onResume);
    document.addEventListener("visibilitychange", onResume);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("pointerdown", onGesture);
      window.removeEventListener("keydown", onGesture);
      window.removeEventListener("pageshow", onResume);
      document.removeEventListener("visibilitychange", onResume);
    };
  }, []);
}

import { useEffect, useRef } from "react";
import { selectBackDepth, useTimelineStore } from "../store/timeline";
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

const isSentinel = () =>
  Boolean((history.state as { __nav?: boolean } | null)?.__nav);

/** 브라우저/시스템 뒤로가기 트랩 + 최상위 종료 확인 — **히스토리 깊이 미러링**.
 *
 * 상태 기반 SPA라 화면 이동이 URL 히스토리에 안 남는다. 예전 구현은 센티넬을
 * "항상 1개"만 두고 popstate마다 재장전했는데, 안드로이드 Chrome의 history
 * manipulation intervention이 **사용자 활성 없이 추가된 항목을 뒤로가기 때
 * 건너뛴다**. popstate(뒤로가기 제스처)는 사용자 활성을 주지 않으므로, popstate
 * 도중의 재장전 센티넬이 건너뛰기 대상이 돼 두 번째 뒤로가기에서 앱이 곧장
 * 종료됐다(폴더 깊이가 다 안 풀림). 이 문제는 설치형 PWA만이 아니라 안드로이드
 * Chrome 탭 전반에 나타난다.
 *
 * 해결: 되돌릴 단계 수(selectBackDepth)만큼 실제 history 항목을 **전진(탭) 시점**
 * 에 쌓는다. 전진 내비게이션은 항상 사용자 탭에서 비롯하므로 그 직후(활성 5초
 * 유효)에 pushState하면 non-skippable 항목이 되어 뒤로가기가 1:1로 확실히
 * 잡힌다. popstate에서는 재장전하지 않고 goBack으로 화면 상태만 한 단계 맞춘다.
 *
 * 항상 backDepth + 1 개의 센티넬을 유지한다. 맨 아래 +1은 "최상위 종료 가드"로,
 * 최상위에서 첫 뒤로가기를 잡아 "한 번 더 누르면 종료" 토스트를 띄운다. 이
 * 가드의 재장전은 popstate 도중이라 안드로이드에서 건너뛰기 대상이 될 수 있으나,
 * 최상위에선 그게 곧 "두 번째 뒤로가기에 종료"라는 의도한 동작과 일치한다.
 */
export function useBackTrap(): void {
  const backDepth = useTimelineStore(selectBackDepth);
  // 리스너/이펙트가 최신 값을 읽도록 ref에 모은다. sync는 setup 이펙트에서 채운다.
  const ref = useRef<{
    backDepth: number;
    activated: boolean;
    exiting: boolean;
    synced: number; // 우리가 쌓은 물리 센티넬 수
    lastRootBack: number;
    sync?: () => void;
  }>({ backDepth, activated: false, exiting: false, synced: 0, lastRootBack: 0 });
  ref.current.backDepth = backDepth;

  useEffect(() => {
    const st = ref.current;
    // 재로딩 등으로 현재 항목이 이미 센티넬이면 가드가 살아남은 것으로 보고
    // 중복 장전을 막는다.
    if (isSentinel()) st.synced = Math.max(st.synced, 1);
    navDbg(
      `load std=${window.matchMedia("(display-mode: standalone)").matches}`,
    );

    // 목표 센티넬 수 = 되돌릴 단계 + 1(최상위 종료 가드). 첫 사용자 상호작용
    // 전에는 장전하지 않는다(활성 없는 센티넬은 건너뛰기 대상이라 무용).
    const target = () => (st.activated && !st.exiting ? st.backDepth + 1 : 0);
    // 부족한 만큼만 push(제거는 popstate가 담당). 전진 탭 직후에 호출되어
    // 사용자 활성이 유효하므로 non-skippable 항목이 된다.
    const sync = () => {
      let pushed = 0;
      while (st.synced < target()) {
        history.pushState({ __nav: true }, "");
        st.synced++;
        pushed++;
      }
      if (pushed) navDbg(`sync +${pushed} synced=${st.synced} dep=${st.backDepth}`);
    };
    st.sync = sync;

    const onGesture = () => {
      const first = !st.activated;
      st.activated = true;
      sync();
      if (first) navDbg(`act synced=${st.synced} hlen=${history.length}`);
    };

    const onPop = () => {
      if (st.exiting) return;
      // 브라우저가 방금 센티넬 하나를 소비했다.
      st.synced = Math.max(0, st.synced - 1);
      const back = useTimelineStore.getState().goBack();
      navDbg(`pop back=${back} synced=${st.synced} dep=${st.backDepth}`);
      if (back) {
        // 화면을 한 단계 되돌렸다. 여기서 재장전하면 안 된다 — popstate 도중의
        // pushState는 사용자 활성이 없어 안드로이드가 건너뛰는(skippable) 센티넬을
        // 만들어 원래 버그가 재발한다. 균형은 자동으로 맞는다: 방금 synced를 1
        // 줄였고, 재렌더에서 backDepth도 1 줄어 depth 이펙트가 target을 맞춘다.
        return;
      }
      // 최상위: 종료 확인(가드 소비됨).
      const now = Date.now();
      if (now - st.lastRootBack < 2500) {
        st.exiting = true;
        navDbg("exit");
        window.removeEventListener("popstate", onPop);
        history.back();
        return;
      }
      st.lastRootBack = now;
      navDbg("toast");
      useToastStore.getState().push("한 번 더 뒤로가기를 누르면 종료됩니다");
      sync(); // 가드 재장전(최상위에선 다음 뒤로가기에 종료 = 의도한 동작)
    };

    const onResume = () => sync();

    // 가능한 이른·다양한 상호작용에서 첫 장전 — 첫 뒤로가기 전에 확실히 사용자
    // 활성을 확보하려고 터치/스크롤/클릭까지 넓게 건다.
    window.addEventListener("popstate", onPop);
    window.addEventListener("pointerdown", onGesture);
    window.addEventListener("touchstart", onGesture, { passive: true });
    window.addEventListener("click", onGesture);
    window.addEventListener("keydown", onGesture);
    window.addEventListener("scroll", onGesture, {
      passive: true,
      capture: true,
    });
    window.addEventListener("pageshow", onResume);
    document.addEventListener("visibilitychange", onResume);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("pointerdown", onGesture);
      window.removeEventListener("touchstart", onGesture);
      window.removeEventListener("click", onGesture);
      window.removeEventListener("keydown", onGesture);
      window.removeEventListener(
        "scroll",
        onGesture,
        { capture: true } as EventListenerOptions,
      );
      window.removeEventListener("pageshow", onResume);
      document.removeEventListener("visibilitychange", onResume);
    };
    // 리스너는 한 번만 등록(최신 상태는 ref로 읽는다).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 되돌릴 깊이가 바뀌면(전진 내비게이션) 그 즉시 부족한 센티넬을 채운다.
  // 이 이펙트는 탭을 유발한 렌더 직후 실행되어 사용자 활성이 아직 유효하다.
  useEffect(() => {
    ref.current.sync?.();
  }, [backDepth]);
}

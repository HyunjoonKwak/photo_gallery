import { useEffect, useRef } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";
import { useToastStore } from "../store/toast";

/** PWA 자동 업데이트: 새 버전이 배포되면(서비스워커가 새로 대기 상태가 되면)
 * 짧게 안내 토스트를 띄우고 곧바로 새 SW를 적용·새로고침한다. 수동 탭에
 * 의존하지 않으므로 사용자가 놓쳐 옛 캐시에 묶이는 일이 없다. 헤드리스. */
export function PwaUpdater() {
  const pushToast = useToastStore((s) => s.push);
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (!registration) return;
      // 앱을 오래 켜둬도 새 버전을 알아채도록 1시간마다 갱신 확인.
      setInterval(() => registration.update(), 60 * 60_000);
      // 앱이 다시 보일 때(재실행/탭 복귀)마다 업데이트 확인 → 배포가 다음 표시에
      // 곧바로 반영되고, "새로고침해야 새 썸네일/화면이 뜨는" 문제를 없앤다.
      const checkForUpdate = () => {
        if (document.visibilityState === "visible") void registration.update();
      };
      document.addEventListener("visibilitychange", checkForUpdate);
      window.addEventListener("focus", checkForUpdate);
    },
  });

  const applied = useRef(false);
  useEffect(() => {
    if (needRefresh && !applied.current) {
      applied.current = true;
      pushToast("새 버전을 적용합니다…");
      // 짧게 안내를 보여준 뒤 새 SW 적용 + 자동 새로고침.
      window.setTimeout(() => updateServiceWorker(true), 1200);
    }
  }, [needRefresh, pushToast, updateServiceWorker]);

  return null;
}

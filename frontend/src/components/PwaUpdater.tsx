import { useEffect, useRef } from "react";
import { useRegisterSW } from "virtual:pwa-register/react";
import { useToastStore } from "../store/toast";

/** PWA 업데이트 감지 → 토스트 알림. 새 버전이 배포되면(서비스워커가 새로
 * 대기 상태가 되면) "새 버전이 있어요 · 새로고침" 토스트를 띄우고, 누르면 새
 * SW를 적용하고 새로고침한다. 헤드리스(렌더 없음). */
export function PwaUpdater() {
  const pushToast = useToastStore((s) => s.push);
  const {
    needRefresh: [needRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      // 앱을 오래 켜둬도 새 버전을 알아채도록 1시간마다 갱신 확인.
      if (registration) {
        setInterval(() => registration.update(), 60 * 60_000);
      }
    },
  });

  const shown = useRef(false);
  useEffect(() => {
    if (needRefresh && !shown.current) {
      shown.current = true;
      pushToast("새 버전이 있어요. 새로고침하면 적용됩니다.", {
        label: "새로고침",
        run: () => updateServiceWorker(true),
      });
    }
  }, [needRefresh, pushToast, updateServiceWorker]);

  return null;
}

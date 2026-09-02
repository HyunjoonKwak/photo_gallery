import { useEffect, useRef } from "react";

const FOCUSABLE = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

function visibleFocusable(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) => el.getClientRects().length > 0 && el.getAttribute("aria-hidden") !== "true",
  );
}

/**
 * 모달의 초기 포커스·Tab 순환·Esc 닫기·닫은 뒤 포커스 복원을 한 곳에서 처리한다.
 * data-modal-root 중 DOM에서 가장 나중인 것만 키를 받아 중첩 다이얼로그도 안전하다.
 */
export function useDialogFocus<T extends HTMLElement>(
  onClose?: () => void,
  active = true,
) {
  const ref = useRef<T | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;
    const previous =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const isTopmost = () => {
      const roots = document.querySelectorAll<HTMLElement>("[data-modal-root='true']");
      return roots.length > 0 && roots[roots.length - 1] === root;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (!isTopmost()) return;
      if (event.key === "Escape" && closeRef.current) {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = visibleFocusable(root);
      if (focusable.length === 0) {
        event.preventDefault();
        root.focus({ preventScroll: true });
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    const frame = window.requestAnimationFrame(() => {
      const preferred = root.querySelector<HTMLElement>("[data-autofocus='true']");
      const target =
        preferred && preferred.getClientRects().length > 0
          ? preferred
          : visibleFocusable(root)[0] ?? root;
      target.focus({ preventScroll: true });
    });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      if (previous?.isConnected) previous.focus({ preventScroll: true });
    };
  }, [active]);

  return ref;
}

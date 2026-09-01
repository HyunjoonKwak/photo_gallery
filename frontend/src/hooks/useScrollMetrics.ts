import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { UIEvent } from "react";

/**
 * 스크롤 상자의 «얼마나 크고 지금 어디쯤인가» — 스크러버 레일이 필요로 하는
 * 두 값(보이는 높이·스크롤 위치)과 요소 참조를 함께 준다.
 *
 * 요소는 **콜백 ref** 로 잡는다. `useRef` + `useLayoutEffect(deps: [])` 로 하면
 * 스크롤 상자가 조건부로 다시 마운트될 때(키 변경·렌즈 전환) 옛 요소를 계속
 * 재게 되고, 레일 길이가 0 으로 굳는다.
 */
export function useScrollMetrics() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const setRef = useCallback((node: HTMLDivElement | null) => {
    ref.current = node;
    setEl(node);
  }, []);

  const [viewportH, setViewportH] = useState(0);
  const [scrollTop, setScrollTop] = useState(0);

  useLayoutEffect(() => {
    if (!el) return;
    setViewportH(el.clientHeight);
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);

  const onScroll = useCallback((e: UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  return { ref, setRef, el, viewportH, scrollTop, onScroll };
}

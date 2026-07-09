import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { useVirtualizer } from "@tanstack/react-virtual";

/** Row-level virtualizer for grids that live INSIDE a larger scroll container
 * (breadcrumb/subfolder cards above, grid below — FolderPane·SearchView·뷰어
 * 폴더). 1000+장 폴더가 셀 전량을 마운트하며 얼던 문제(F절 Phase B)를 행 단위
 * 마운트로 바꾼다. 행 높이는 호출자가 이미 알고 있어(justified rows) 측정이
 * 필요 없다. scrollMargin은 그리드 시작점의 컨테이너 내 오프셋.
 */
export function VirtualRows({
  count,
  heightOf,
  scrollRef,
  renderRow,
  overscan = 6,
}: {
  count: number;
  heightOf: (index: number) => number;
  scrollRef: RefObject<HTMLElement | null>;
  renderRow: (index: number) => ReactNode;
  overscan?: number;
}) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [margin, setMargin] = useState(0);
  // 스크롤 요소는 '부모'의 ref — 자식(여기)의 마운트 시점엔 아직 attach 전이라
  // getScrollElement가 null이 되어 가상화기가 초기화되지 않는다(2026-07-10 실측:
  // 행 0개 렌더). passive effect(전체 커밋 후)에서 state로 승격해 재초기화시킨다.
  const [scrollEl, setScrollEl] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (scrollRef.current !== scrollEl) setScrollEl(scrollRef.current);
  });

  // 그리드 위 콘텐츠(브레드크럼·하위폴더 목록)의 높이가 바뀌면 오프셋도 변한다
  // — 매 렌더에서 재측정하되 값이 같으면 setState가 bail해 루프는 없다.
  useLayoutEffect(() => {
    const el = wrapRef.current;
    const sc = scrollRef.current;
    if (!el || !sc) return;
    const m = Math.round(
      el.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop,
    );
    setMargin((prev) => (prev === m ? prev : m));
  });

  const virtualizer = useVirtualizer({
    count,
    getScrollElement: () => scrollEl,
    estimateSize: heightOf,
    overscan,
    scrollMargin: margin,
  });

  // 행 구성이 바뀌면(폭 변화로 재레이아웃 등) 캐시된 높이를 다시 읽게 한다.
  useLayoutEffect(() => {
    virtualizer.measure();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count, heightOf]);

  return (
    <div ref={wrapRef} style={{ position: "relative", height: virtualizer.getTotalSize() }}>
      {virtualizer.getVirtualItems().map((vi) => (
        <div
          key={vi.key}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            transform: `translateY(${vi.start - margin}px)`,
          }}
        >
          {renderRow(vi.index)}
        </div>
      ))}
    </div>
  );
}

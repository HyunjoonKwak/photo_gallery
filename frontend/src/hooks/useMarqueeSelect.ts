import { useEffect, useRef, useState, type RefObject } from "react";
import type { TimelineRowModel } from "../lib/rowModel";
import { useTimelineStore } from "../store/timeline";

export interface MarqueeRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Finder식 마우스 영역(러버밴드) 선택 — 폴더 분류 사진 그리드용.
 *
 * 빈 공간에서 드래그 시작(사진 위 드래그는 dnd-kit 이동이 가져감), 셀 좌표는
 * DOM이 아니라 **레이아웃 데이터(photoRows)** 로 판정하므로 가상화로 화면 밖에
 * 있는 사진도 정확히 선택된다. Shift+드래그=기존 선택에 추가. 마우스 전용
 * (pointer: fine). 컨테이너 가장자리에 닿으면 자동 스크롤.
 */
export function useMarqueeSelect({
  scrollRef,
  gridRef,
  photoRows,
  enabled,
}: {
  scrollRef: RefObject<HTMLElement | null>;
  gridRef: RefObject<HTMLElement | null>;
  photoRows: Extract<TimelineRowModel, { kind: "photos" }>[];
  enabled: boolean;
}): MarqueeRect | null {
  const [rect, setRect] = useState<MarqueeRect | null>(null);
  const rowsRef = useRef(photoRows);
  rowsRef.current = photoRows;

  useEffect(() => {
    if (!enabled) return;
    if (!window.matchMedia("(pointer: fine)").matches) return;
    const sc = scrollRef.current;
    if (!sc) return;

    let startX = 0; // 콘텐츠 좌표(스크롤 보정 포함)
    let startY = 0;
    let active = false; // 8px 임계 통과 후에만 발동(배경 클릭 보존)
    let base: Set<string> = new Set(); // Shift 시작 시점의 기존 선택
    let raf = 0;

    const contentPoint = (e: MouseEvent) => {
      const box = sc.getBoundingClientRect();
      return {
        x: e.clientX - box.left + sc.scrollLeft,
        y: e.clientY - box.top + sc.scrollTop,
      };
    };

    /** 현재 마퀴 사각형과 교차하는 사진 id — 레이아웃 데이터로 계산. */
    const hitIds = (r: MarqueeRect): string[] => {
      const grid = gridRef.current;
      if (!grid) return [];
      const gbox = grid.getBoundingClientRect();
      const sbox = sc.getBoundingClientRect();
      const gridTop = gbox.top - sbox.top + sc.scrollTop;
      const gridLeft = gbox.left - sbox.left + sc.scrollLeft;
      const out: string[] = [];
      let top = gridTop;
      for (const row of rowsRef.current) {
        const bottom = top + row.height;
        if (bottom >= r.top && top <= r.top + r.height) {
          for (const cell of row.cells) {
            const cl = gridLeft + cell.left;
            if (
              cl + cell.width >= r.left &&
              cl <= r.left + r.width &&
              top + cell.height >= r.top &&
              top <= r.top + r.height
            ) {
              out.push(cell.item.id);
            }
          }
        }
        top = bottom;
      }
      return out;
    };

    const onMove = (e: MouseEvent) => {
      const p = contentPoint(e);
      if (!active) {
        if (Math.abs(p.x - startX) < 8 && Math.abs(p.y - startY) < 8) return;
        active = true;
      }
      // 가장자리 자동 스크롤(드래그로 화면 밖까지 훑기).
      const box = sc.getBoundingClientRect();
      if (e.clientY > box.bottom - 28) sc.scrollTop += 16;
      else if (e.clientY < box.top + 28) sc.scrollTop -= 16;

      const r: MarqueeRect = {
        left: Math.min(startX, p.x),
        top: Math.min(startY, p.y),
        width: Math.abs(p.x - startX),
        height: Math.abs(p.y - startY),
      };
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        setRect(r);
        const ids = hitIds(r);
        useTimelineStore
          .getState()
          .replaceSelection([...new Set([...base, ...ids])]);
      });
      e.preventDefault();
    };

    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      cancelAnimationFrame(raf);
      setRect(null);
    };

    const onDown = (e: MouseEvent) => {
      if (e.button !== 0) return;
      const t = e.target as HTMLElement;
      // 사진(버튼)·입력·툴바/다이얼로그(data-no-boxselect)에서는 시작하지 않음
      // — 사진 위 드래그는 dnd 이동, 여기는 '빈 공간' 러버밴드 전용.
      // PhotoCell 루트는 button이 아니라 div[data-photo-id](dnd 드래그 소스)
      // — 셀 위 드래그는 이동(dnd)이므로 러버밴드를 시작하지 않는다.
      if (t.closest("button, input, a, [data-no-boxselect], [data-photo-id]"))
        return;
      const p = contentPoint(e);
      startX = p.x;
      startY = p.y;
      active = false;
      base = e.shiftKey
        ? new Set(useTimelineStore.getState().selected)
        : new Set();
      if (!e.shiftKey) useTimelineStore.getState().clearSelection();
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    };

    sc.addEventListener("mousedown", onDown);
    return () => {
      sc.removeEventListener("mousedown", onDown);
      onUp();
    };
  }, [enabled, scrollRef, gridRef]);

  return rect;
}

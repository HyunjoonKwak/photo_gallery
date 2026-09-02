import { useEffect, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useTimelineStore } from "../../store/timeline";
import { Thumb } from "./Thumb";

/** 한 칸의 크기 (px). 세로는 여백까지 합쳐 STRIP_H 가 된다. */
const W = 88;
const H = 60;
const GAP = 4;
/** 스트립이 차지하는 전체 높이.
 * ⚠ 라이트박스가 사진을 이만큼 위로 물리는 값(`sm:max-h-[calc(90vh-76px)]`)과
 * 짝이다. Tailwind 는 소스의 **리터럴**만 훑어 클래스를 만들어서 이 상수를
 * 거기에 끼워 넣을 수 없다 — 값을 바꾸면 Lightbox 의 그 클래스도 함께 고칠 것. */
const STRIP_H = H + 16;

/**
 * 라이트박스 아래 필름스트립 — 지금 보는 사진 둘레의 앞뒤.
 *
 * 한 장을 크게 띄우면 앞뒤 맥락이 사라진다. 어디쯤 보고 있는지, 다음이
 * 무엇인지 알려면 닫고 그리드로 나가야 했다. 스트립은 그 맥락을 좁고 길게
 * 되돌려 준다.
 *
 * 목록은 그리드와 **같은 배열**(`orderedIds`)을 본다. 따로 읽지 않으니
 * 정렬·필터·검색 결과가 저절로 맞고, 그리드가 바뀌면 스트립도 함께 바뀐다.
 */
export function LightboxFilmstrip() {
  const orderedIds = useTimelineStore((s) => s.orderedIds);
  const itemsById = useTimelineStore((s) => s.itemsById);
  const lightboxId = useTimelineStore((s) => s.lightboxId);
  const openLightbox = useTimelineStore((s) => s.openLightbox);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const virtualizer = useVirtualizer({
    horizontal: true,
    count: orderedIds.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => W + GAP,
    overscan: 8,
  });

  const index = lightboxId ? orderedIds.indexOf(lightboxId) : -1;
  // 보는 사진이 바뀌면 스트립이 따라간다 — 좌우 화살표로 넘겨도 초점이
  // 화면 밖으로 새지 않는다.
  useEffect(() => {
    if (index >= 0) virtualizer.scrollToIndex(index, { align: "center" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  if (orderedIds.length < 2) return null;

  return (
    <div
      data-no-boxselect
      ref={scrollRef}
      className="scroll-thin w-full overflow-x-auto overflow-y-hidden bg-black/70 px-2 py-2 backdrop-blur"
      style={{ height: STRIP_H }}
    >
      <div
        style={{
          width: virtualizer.getTotalSize(),
          height: H,
          position: "relative",
        }}
      >
        {virtualizer.getVirtualItems().map((v) => {
          const id = orderedIds[v.index];
          const it = itemsById.get(id);
          if (!it) return null;
          const active = id === lightboxId;
          return (
            <button
              key={id}
              onClick={() => openLightbox(id)}
              title={it.filename}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: W,
                height: H,
                transform: `translateX(${v.start}px)`,
              }}
              className={`overflow-hidden rounded transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
                active
                  ? "opacity-100 ring-2 ring-white"
                  : "opacity-55 hover:opacity-90"
              }`}
            >
              <Thumb item={it} rounded="rounded" />
            </button>
          );
        })}
      </div>
    </div>
  );
}

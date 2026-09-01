import { useEffect, useRef, useState } from "react";
import { thumbnailUrl, videoUrl } from "../../api/client";
import { formatDuration } from "../../lib/dates";
import { thumbhashToUrl } from "../../lib/thumbhash";
import {
  claimHoverPreview,
  HOVER_DELAY_MS,
  prefersReducedMotion,
  releaseHoverPreview,
} from "../../lib/hoverPreview";
import type { PhotoItem, Space } from "../../api/types";

/** 순수 썸네일 표현 (3단계 로딩 + 폴백 + 비디오 배지). 위치/크기는 부모가
 * 정하고(h-full/w-full 채움), 이 컴포넌트는 내용만 그린다. PhotoCell(선택/
 * 드래그)과 뷰어/커버 셀이 공유한다.
 *
 * 동영상은 마우스를 400ms 올리고 있으면 소리 없이 재생해 보여 준다 — 정지
 * 화면만으로는 어떤 장면인지 알 수 없다. 재생권은 앱 전체에서 하나뿐이라
 * (`hoverPreview`) 그리드를 훑어도 영상이 겹쳐 돌지 않는다. */
export function Thumb({
  item,
  space,
  rounded = "rounded-sm",
}: {
  item: PhotoItem;
  space?: Space;
  rounded?: string;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const sp = item.space ?? space ?? "team";
  const noThumb = failed || !item.cache_key;
  const isVideo = item.type === "video";

  // 미리보기 — 이 타일이 사는 동안 같은 열쇠여야 재생권을 알아본다.
  const previewKey = useRef({});
  const timer = useRef<number | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const stopPreview = () => {
    if (timer.current != null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    releaseHoverPreview(previewKey.current);
    setPreviewing(false);
  };

  // 타일이 사라질 때(가상화 스크롤아웃 포함) 예약된 재생도 함께 거둔다.
  useEffect(() => stopPreview, []);

  const beginPreview = (e: React.PointerEvent) => {
    // 손가락·펜은 hover 가 없다 — 탭이 재생으로 새는 것을 막는다.
    if (!isVideo || noThumb || e.pointerType !== "mouse") return;
    if (prefersReducedMotion()) return;
    if (timer.current != null) return;
    timer.current = window.setTimeout(() => {
      timer.current = null;
      claimHoverPreview(previewKey.current, () => setPreviewing(false));
      setPreviewing(true);
    }, HOVER_DELAY_MS);
  };

  return (
    <div
      onPointerEnter={beginPreview}
      onPointerLeave={stopPreview}
      className={`relative h-full w-full overflow-hidden ${rounded}`}
      style={{
        backgroundColor: item.placeholder_color ?? "#e2e8f0",
        backgroundImage:
          !loaded && item.thumbhash
            ? `url(${thumbhashToUrl(item.thumbhash) ?? ""})`
            : undefined,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {noThumb ? (
        <div
          className={`flex h-full w-full items-center justify-center ${
            isVideo ? "bg-slate-800 text-white/90" : "bg-slate-200 text-slate-400"
          }`}
        >
          <span className="text-2xl leading-none">{isVideo ? "▶" : "🖼"}</span>
        </div>
      ) : (
        <img
          src={thumbnailUrl(sp, item.id, item.cache_key, "sm")}
          alt={item.filename}
          loading="lazy"
          decoding="async"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          className={`h-full w-full object-cover transition-opacity duration-200 ${
            loaded ? "opacity-100" : "opacity-0"
          }`}
        />
      )}
      {previewing && (
        <video
          src={videoUrl(sp, item.id, item.cache_key)}
          autoPlay
          muted
          loop
          playsInline
          // 재생권을 잡은 뒤에야 마운트되므로 여기서 미리 받아 둘 것이 없다.
          preload="none"
          className="pointer-events-none absolute inset-0 h-full w-full object-cover"
        />
      )}
      {isVideo && (
        <span className="pointer-events-none absolute bottom-1 right-1 flex items-center gap-1 rounded-full bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
          ▶{item.duration_ms != null && ` ${formatDuration(item.duration_ms)}`}
        </span>
      )}
    </div>
  );
}

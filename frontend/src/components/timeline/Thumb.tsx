import { useState } from "react";
import { thumbnailUrl } from "../../api/client";
import { formatDuration } from "../../lib/dates";
import { thumbhashToUrl } from "../../lib/thumbhash";
import type { PhotoItem, Space } from "../../api/types";

/** 순수 썸네일 표현 (3단계 로딩 + 폴백 + 비디오 배지). 위치/크기는 부모가
 * 정하고(h-full/w-full 채움), 이 컴포넌트는 내용만 그린다. PhotoCell(선택/
 * 드래그)과 뷰어/커버 셀이 공유한다. */
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

  return (
    <div
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
            item.type === "video"
              ? "bg-slate-800 text-white/90"
              : "bg-slate-200 text-slate-400"
          }`}
        >
          <span className="text-2xl leading-none">
            {item.type === "video" ? "▶" : "🖼"}
          </span>
        </div>
      ) : (
        <img
          src={thumbnailUrl(sp, item.id, item.cache_key, "sm")}
          alt={item.filename}
          loading="lazy"
          draggable={false}
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          className={`h-full w-full object-cover transition-opacity duration-200 ${
            loaded ? "opacity-100" : "opacity-0"
          }`}
        />
      )}
      {item.type === "video" && (
        <span className="pointer-events-none absolute bottom-1 right-1 flex items-center gap-1 rounded-full bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
          ▶{item.duration_ms != null && ` ${formatDuration(item.duration_ms)}`}
        </span>
      )}
    </div>
  );
}

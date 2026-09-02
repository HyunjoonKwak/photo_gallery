import { memo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { thumbnailUrl } from "../../api/client";
import { formatDuration } from "../../lib/dates";
import { thumbhashToUrl } from "../../lib/thumbhash";
import { useTimelineStore } from "../../store/timeline";
import type { CellLayout } from "../../lib/rowModel";

/** One photo in the grid.
 *
 * Interaction split (IMPROVEMENTS B-3, Google Photos pattern):
 * - photo click opens the lightbox; the hover check-circle selects
 * - once selection mode is active (anything selected), photo clicks toggle
 * - Shift+click extends the range from the anchor
 * Three-stage loading (IMPROVEMENTS B-2): blurred thumbhash (when the dedup
 * scan has hashed the item) or placeholder color → sm thumbnail fades in →
 * xl in the lightbox.
 */
export const PhotoCell = memo(function PhotoCell({
  cell,
  dndEnabled,
}: {
  cell: CellLayout;
  dndEnabled: boolean;
}) {
  const { item } = cell;
  const globalSpace = useTimelineStore((s) => s.space);
  const space = item.space ?? globalSpace;
  const selected = useTimelineStore((s) => s.selected.has(item.id));
  const previewed = useTimelineStore((s) => s.previewIds.has(item.id));
  const selectionMode = useTimelineStore((s) => s.selected.size > 0);
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    isDragging,
  } = useDraggable({
    id: item.id,
    disabled: !dndEnabled,
  });
  const [loaded, setLoaded] = useState(false);
  // Synology가 poster를 생성하지 않은 아이템(개인 공간 동영상의 38%가 이렇다 —
  // 2026-07-04 실 NAS 확인)은 썸네일 요청이 404다. 빈 회색칸 대신 폴백 타일로.
  const [failed, setFailed] = useState(false);
  const noThumb = failed || !item.cache_key;

  const onCellClick = (e: React.MouseEvent) => {
    const store = useTimelineStore.getState();
    if (store.selected.size > 0 || e.shiftKey) {
      store.selectClick(item.id, e.shiftKey);
    } else {
      store.openLightbox(item.id);
    }
  };

  const onCheckClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    useTimelineStore.getState().selectClick(item.id, e.shiftKey);
  };

  return (
    <div
      ref={setNodeRef}
      data-photo-id={item.id}
      data-draggable={dndEnabled ? "true" : undefined}
      onMouseEnter={() => useTimelineStore.getState().setHover(item.id)}
      onMouseLeave={() => useTimelineStore.getState().setHover(null)}
      className={`group absolute top-0 select-none overflow-hidden rounded-sm transition-shadow ${
        selected ? "ring-4 ring-inset ring-blue-500" : ""
      } ${previewed && !selected ? "ring-4 ring-inset ring-blue-300" : ""} ${
        isDragging ? "opacity-40" : ""
      }`}
      style={{
        left: cell.left,
        width: cell.width,
        height: cell.height,
        // iOS: long-press starts our drag, not the image save callout.
        WebkitTouchCallout: "none",
        backgroundColor: item.placeholder_color ?? "#e2e8f0",
        backgroundImage:
          !loaded && item.thumbhash
            ? `url(${thumbhashToUrl(item.thumbhash) ?? ""})`
            : undefined,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      <button
        ref={setActivatorNodeRef}
        {...listeners}
        {...attributes}
        type="button"
        aria-label={item.filename}
        onClick={onCellClick}
        className="absolute inset-0 h-full w-full cursor-pointer overflow-hidden rounded-sm text-left focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-inset focus-visible:ring-blue-300"
      >
        {noThumb ? (
          // 썸네일 없음: 동영상은 필름 톤 배경 + 큰 ▶, 사진은 파일 아이콘.
          <div
            className={`flex h-full w-full items-center justify-center ${
              item.type === "video"
                ? "bg-slate-800 text-white/90"
                : "bg-slate-200 text-slate-400"
            } ${selected ? "scale-90 rounded" : ""}`}
          >
            <span className="text-2xl leading-none">
              {item.type === "video" ? "▶" : "🖼"}
            </span>
          </div>
        ) : (
          <img
            src={thumbnailUrl(space, item.id, item.cache_key, "sm")}
            alt=""
            loading="lazy"
            decoding="async"
            draggable={false}
            onLoad={() => setLoaded(true)}
            onError={() => setFailed(true)}
            className={`h-full w-full object-cover transition-all duration-200 ${
              loaded ? "opacity-100" : "opacity-0"
            } ${selected ? "scale-90 rounded" : ""}`}
          />
        )}
        {item.type === "video" && (
          <span className="pointer-events-none absolute bottom-1.5 right-1.5 flex items-center gap-1 rounded-full bg-black/60 px-1.5 py-0.5 text-[10px] font-medium text-white">
            ▶{item.duration_ms != null && ` ${formatDuration(item.duration_ms)}`}
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={onCheckClick}
        onPointerDown={(e) => e.stopPropagation()}
        aria-label={selected ? "선택 해제" : "선택"}
        className={`absolute left-0.5 top-0.5 flex h-10 w-10 items-center justify-center rounded-full transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 ${
          selected
            ? "opacity-100"
            : selectionMode
              ? "opacity-100 sm:opacity-80 sm:hover:opacity-100"
              : "opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
        }`}
      >
        <span
          className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold shadow-sm ${
            selected
              ? "bg-blue-600 text-white"
              : "bg-white/85 text-slate-500 ring-1 ring-black/10"
          }`}
        >
          ✓
        </span>
      </button>
    </div>
  );
});

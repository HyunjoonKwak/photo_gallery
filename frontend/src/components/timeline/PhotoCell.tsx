import { memo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { thumbnailUrl } from "../../api/client";
import { useTimelineStore } from "../../store/timeline";
import type { CellLayout } from "../../lib/rowModel";

/** One photo in the grid.
 *
 * Interaction split (IMPROVEMENTS B-3, Google Photos pattern):
 * - photo click opens the lightbox; the hover check-circle selects
 * - once selection mode is active (anything selected), photo clicks toggle
 * - Shift+click extends the range from the anchor
 * Two-stage loading: placeholder color first, thumbnail fades in on load
 * (thumbhash replaces the color when the photo_cache pipeline lands).
 */
export const PhotoCell = memo(function PhotoCell({ cell }: { cell: CellLayout }) {
  const { item } = cell;
  const space = useTimelineStore((s) => s.space);
  const selected = useTimelineStore((s) => s.selected.has(item.id));
  const previewed = useTimelineStore((s) => s.previewIds.has(item.id));
  const selectionMode = useTimelineStore((s) => s.selected.size > 0);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: item.id,
  });
  const [loaded, setLoaded] = useState(false);

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
      {...listeners}
      {...attributes}
      data-photo-id={item.id}
      data-draggable="true"
      onClick={onCellClick}
      onMouseEnter={() => useTimelineStore.getState().setHover(item.id)}
      onMouseLeave={() => useTimelineStore.getState().setHover(null)}
      className={`group absolute top-0 cursor-pointer select-none overflow-hidden rounded-sm outline-none transition-shadow ${
        selected ? "ring-4 ring-inset ring-blue-500" : ""
      } ${previewed && !selected ? "ring-4 ring-inset ring-blue-300" : ""} ${
        isDragging ? "opacity-40" : ""
      }`}
      style={{
        left: cell.left,
        width: cell.width,
        height: cell.height,
        backgroundColor: item.placeholder_color ?? "#e2e8f0",
      }}
    >
      <img
        src={thumbnailUrl(space, item.id, item.cache_key, "sm")}
        alt={item.filename}
        loading="lazy"
        draggable={false}
        onLoad={() => setLoaded(true)}
        className={`h-full w-full object-cover transition-all duration-200 ${
          loaded ? "opacity-100" : "opacity-0"
        } ${selected ? "scale-90 rounded" : ""}`}
      />
      <button
        onClick={onCheckClick}
        aria-label={selected ? "선택 해제" : "선택"}
        className={`absolute left-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold transition-opacity ${
          selected
            ? "bg-blue-600 text-white opacity-100"
            : selectionMode
              ? "bg-white/80 text-slate-500 opacity-70 hover:opacity-100"
              : "bg-white/80 text-slate-500 opacity-0 group-hover:opacity-100"
        }`}
      >
        ✓
      </button>
    </div>
  );
});

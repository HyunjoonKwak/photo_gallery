import { thumbnailUrl } from "../../api/client";
import { useTimelineStore } from "../../store/timeline";
import type { PhotoItem } from "../../api/types";

/** Drag ghost: a small stack of the first thumbnails + "n장" badge, with the
 * move/copy mode shown live (⌥/Alt = copy, Finder convention — IMPROVEMENTS
 * B-4). Rendered inside dnd-kit's DragOverlay, which is mandatory here because
 * the source cell can be unmounted by virtualization mid-drag.
 */
export function DragOverlayContent({
  ids,
  copyMode,
}: {
  ids: string[];
  copyMode: boolean;
}) {
  const itemsById = useTimelineStore((s) => s.itemsById);
  const space = useTimelineStore((s) => s.space);
  const items = ids
    .slice(0, 3)
    .map((id) => itemsById.get(id))
    .filter((i): i is PhotoItem => Boolean(i));

  return (
    <div className="pointer-events-none relative h-24 w-24">
      {items.map((item, i) => (
        <img
          key={item.id}
          src={thumbnailUrl(item.space ?? space, item.id, item.cache_key, "sm")}
          alt=""
          className="absolute inset-0 h-24 w-24 rounded-lg border-2 border-white object-cover shadow-lg"
          style={{
            transform: `translate(${i * 5}px, ${i * 5}px) rotate(${(i - 1) * 4}deg)`,
            zIndex: items.length - i,
          }}
        />
      ))}
      <div className="absolute -right-3 -top-3 z-10 rounded-full bg-blue-600 px-2 py-0.5 text-xs font-bold text-white shadow">
        {ids.length}장
      </div>
      <div className="absolute -bottom-2 left-1/2 z-10 -translate-x-1/2 rounded-full bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-white shadow">
        {copyMode ? "+ 복사" : "이동"}
      </div>
    </div>
  );
}

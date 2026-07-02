import { useEffect } from "react";
import { thumbnailUrl } from "../api/client";
import { useTimelineStore } from "../store/timeline";
import { formatBytes } from "../lib/dates";

/** Minimal lightbox: xl image, ←/→ stepping, ESC close, neighbor prefetch.
 * The full spec version (EXIF side panel via `i`, delete-and-advance) lands
 * with the file-operation step — this establishes the click-to-open semantics.
 */
export function Lightbox() {
  const item = useTimelineStore((s) =>
    s.lightboxId ? (s.itemsById.get(s.lightboxId) ?? null) : null,
  );
  const space = useTimelineStore((s) => s.space);

  // Arrow-key stepping (ESC is handled by the screen-level handler).
  useEffect(() => {
    if (!item) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") useTimelineStore.getState().stepLightbox(1);
      if (e.key === "ArrowLeft") useTimelineStore.getState().stepLightbox(-1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [item]);

  // Prefetch neighbors so stepping feels instant.
  useEffect(() => {
    if (!item) return;
    const s = useTimelineStore.getState();
    const idx = s.orderedIds.indexOf(item.id);
    for (const i of [idx - 1, idx + 1]) {
      const neighbor = s.itemsById.get(s.orderedIds[i] ?? "");
      if (neighbor) {
        new Image().src = thumbnailUrl(space, neighbor.id, neighbor.cache_key, "xl");
      }
    }
  }, [item, space]);

  if (!item) return null;

  const close = () => useTimelineStore.getState().closeLightbox();
  const navBtn =
    "absolute top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-3 text-2xl text-white/80 hover:text-white hover:bg-black/70";

  return (
    <div
      data-no-boxselect
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/95"
      onClick={close}
    >
      <img
        src={thumbnailUrl(space, item.id, item.cache_key, "xl")}
        alt={item.filename}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] max-w-[94vw] object-contain"
      />
      <button
        aria-label="이전 사진"
        className={`${navBtn} left-4`}
        onClick={(e) => {
          e.stopPropagation();
          useTimelineStore.getState().stepLightbox(-1);
        }}
      >
        ‹
      </button>
      <button
        aria-label="다음 사진"
        className={`${navBtn} right-4`}
        onClick={(e) => {
          e.stopPropagation();
          useTimelineStore.getState().stepLightbox(1);
        }}
      >
        ›
      </button>
      <button
        aria-label="닫기"
        className="absolute right-4 top-4 rounded-full bg-black/50 p-2 text-xl text-white/80 hover:text-white"
        onClick={close}
      >
        ✕
      </button>
      <div
        className="absolute bottom-0 left-0 right-0 flex justify-center gap-4 bg-gradient-to-t from-black/80 to-transparent px-4 py-3 text-xs text-slate-300"
        onClick={(e) => e.stopPropagation()}
      >
        <span className="font-medium text-white">{item.filename}</span>
        <span>{item.taken_at.replace("T", " ")}</span>
        <span>
          {item.width}×{item.height}
        </span>
        {item.size != null && <span>{formatBytes(item.size)}</span>}
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";
import { FolderPanel } from "./FolderPanel";
import { Lightbox } from "./Lightbox";
import { TimelineView } from "./timeline/TimelineView";
import { DragOverlayContent } from "./timeline/DragOverlayContent";
import { SelectionActionBar } from "./timeline/SelectionActionBar";

/** Composes the timeline screen: folder drop panel + grid + DnD + keyboard.
 *
 * DnD decisions (IMPROVEMENTS B-4/C): PointerSensor with an 8px activation
 * distance keeps plain clicks working on draggable cells and separates drag
 * from marquee selection; DragOverlay is mandatory because virtualization can
 * unmount the source cell mid-drag; Alt(⌥) switches move→copy, shown live on
 * the ghost. Drops only toast for now — the CopyMove/Delete + undo log step
 * wires them to real operations.
 */
export function TimelineScreen() {
  const space = useTimelineStore((s) => s.space);
  const foldersQuery = useQuery({ queryKey: ["folders"], queryFn: api.folders });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );
  const [dragIds, setDragIds] = useState<string[] | null>(null);
  const [altHeld, setAltHeld] = useState(false);

  // Global keys: Shift (range preview), Alt (copy mode), Escape (close/clear).
  useEffect(() => {
    const onDown = (e: KeyboardEvent) => {
      if (e.key === "Shift") useTimelineStore.getState().setShift(true);
      if (e.key === "Alt") setAltHeld(true);
      if (e.key === "Escape") {
        const s = useTimelineStore.getState();
        if (s.lightboxId) s.closeLightbox();
        else s.clearSelection();
      }
    };
    const onUp = (e: KeyboardEvent) => {
      if (e.key === "Shift") useTimelineStore.getState().setShift(false);
      if (e.key === "Alt") setAltHeld(false);
    };
    window.addEventListener("keydown", onDown);
    window.addEventListener("keyup", onUp);
    return () => {
      window.removeEventListener("keydown", onDown);
      window.removeEventListener("keyup", onUp);
    };
  }, []);

  const onDragStart = (e: DragStartEvent) => {
    const id = String(e.active.id);
    const store = useTimelineStore.getState();
    // Finder convention: dragging an unselected photo makes it the selection.
    if (!store.selected.has(id)) store.replaceSelection([id]);
    setDragIds([...useTimelineStore.getState().selected]);
  };

  const onDragEnd = (e: DragEndEvent) => {
    const ids = dragIds;
    setDragIds(null);
    const overId = e.over?.id;
    if (!ids || typeof overId !== "string" || !overId.startsWith("folder:")) return;
    const folder = foldersQuery.data?.folders.find(
      (f) => `folder:${f.id}` === overId,
    );
    if (!folder) return;
    useToastStore
      .getState()
      .push(
        `${ids.length}장을 "${folder.name}" 폴더로 ${altHeld ? "복사" : "이동"} — 파일 작업 API는 다음 단계에서 연결됩니다.`,
      );
  };

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onDragCancel={() => setDragIds(null)}
      >
        <div className="flex h-full">
          <FolderPanel />
          <main className="relative min-w-0 flex-1">
            {/* key=space: switching tabs resets lazy-load/selection state cleanly */}
            <TimelineView key={space} />
          </main>
        </div>
        <DragOverlay dropAnimation={null}>
          {dragIds && <DragOverlayContent ids={dragIds} copyMode={altHeld} />}
        </DragOverlay>
      </DndContext>
      <SelectionActionBar />
      <Lightbox />
    </>
  );
}

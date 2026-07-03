import { useEffect, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { ClassifyView } from "./ClassifyView";
import { DedupView } from "./DedupView";
import { FolderPanel } from "./FolderPanel";
import { FolderView } from "./FolderView";
import { SearchView } from "./SearchView";
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
  const viewMode = useTimelineStore((s) => s.viewMode);
  const ops = useFileOps();

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );
  const [dragIds, setDragIds] = useState<string[] | null>(null);
  const [altHeld, setAltHeld] = useState(false);
  // Whether the drag currently hovers a valid folder target — drives the
  // ghost's drop feedback (B-4: 무효 대상 안내).
  const [overFolder, setOverFolder] = useState(false);

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

  const onDragOver = (e: DragOverEvent) => {
    const overId = e.over?.id;
    setOverFolder(
      Boolean(e.over?.data.current?.folderId) ||
        (typeof overId === "string" && overId.startsWith("folder:")),
    );
  };

  const onDragEnd = (e: DragEndEvent) => {
    const ids = dragIds;
    setDragIds(null);
    setOverFolder(false);
    // Dest folder: droppable data first (dual-pane cards/backgrounds carry it
    // with pane-unique ids), else the legacy "folder:<id>" id convention.
    const dataFolderId = e.over?.data.current?.folderId as string | undefined;
    const overId = e.over?.id;
    const folderId =
      dataFolderId ??
      (typeof overId === "string" && overId.startsWith("folder:")
        ? overId.slice("folder:".length)
        : null);
    if (!ids || !folderId) return;
    // Finder convention: drag = move, ⌥ = copy. No confirmation — undo toast.
    ops.move(ids, folderId, altHeld);
  };

  return (
    <>
      <DndContext
        sensors={sensors}
        collisionDetection={pointerWithin}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={() => {
          setDragIds(null);
          setOverFolder(false);
        }}
      >
        {viewMode === "timeline" && (
          <div className="flex h-full">
            <FolderPanel />
            <main className="relative min-w-0 flex-1">
              {/* key=space: switching tabs resets lazy-load/selection state cleanly */}
              <TimelineView key={space} />
            </main>
          </div>
        )}
        {viewMode === "folders" && <FolderView />}
        {viewMode === "dedup" && <DedupView key={space} />}
        {viewMode === "search" && (
          <div className="flex h-full">
            {/* Folder panel doubles as drop target for organizing results. */}
            <FolderPanel />
            <main className="relative min-w-0 flex-1">
              <SearchView key={space} />
            </main>
          </div>
        )}
        {viewMode === "classify" && (
          <div className="flex h-full">
            {/* Same folder panel as the timeline: drop target + quick jump,
             * so classified groups can be dragged straight into folders. */}
            <FolderPanel />
            <main className="relative min-w-0 flex-1">
              <ClassifyView key={space} />
            </main>
          </div>
        )}
        <DragOverlay dropAnimation={null}>
          {dragIds && (
            <DragOverlayContent
              ids={dragIds}
              copyMode={altHeld}
              overValid={overFolder}
            />
          )}
        </DragOverlay>
      </DndContext>
      <SelectionActionBar />
      <Lightbox />
    </>
  );
}

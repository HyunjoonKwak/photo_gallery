import { useEffect, useState } from "react";
import {
  DndContext,
  DragOverlay,
  MouseSensor,
  TouchSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { AlbumsScreen } from "./AlbumsScreen";
import { ManageScreen } from "./ManageScreen";
import { ViewerScreen } from "./ViewerScreen";
import { Lightbox } from "./Lightbox";
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
  const section = useTimelineStore((s) => s.section);
  const ops = useFileOps();

  // Mouse: 8px 이동이면 드래그 (클릭과 구분). Touch: 300ms 길게 누른 뒤
  // 끌 때만 드래그 — 일반 스와이프는 브라우저 스크롤로 넘어가야 한다
  // (PointerSensor 하나로 합치면 터치 스크롤이 드래그로 잡혀 선택돼 버림).
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 300, tolerance: 8 },
    }),
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
        {/* 사진·앨범 = 순수 뷰어, 폴더 분류 = 정리(DnD/액션바). */}
        {section === "viewer" && <ViewerScreen key={space} />}
        {section === "albums" && <AlbumsScreen key={space} />}
        {section === "manage" && <ManageScreen />}
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

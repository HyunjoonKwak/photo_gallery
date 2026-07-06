import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api } from "../api/client";
import type { PhotoFolder, Space } from "../api/types";

/** Finder's spring-loaded folders (IMPROVEMENTS B-4): while a drag hovers a
 * collapsed node/card for this long, it opens by itself. */
export const SPRING_MS = 600;

/** Lazy folder tree (IMPROVEMENTS: the real NAS has 1500+ folders, so the tree
 * loads one level at a time — children are fetched only when a node expands).
 * Nodes are drop targets when `droppable`, and selectable via `onSelect`.
 */
export function folderBasename(name: string): string {
  const parts = name.split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : name;
}

function FolderTreeNode({
  folder,
  onSelect,
  selectedId,
  droppable,
  dest = false,
}: {
  folder: PhotoFolder;
  onSelect?: (f: PhotoFolder) => void;
  selectedId?: string;
  droppable: boolean;
  /** true면 현재 스코프(zone/owner)를 붙이지 않고 개인/공용 Photos 트리를
   * 가져온다 — 1차→2차 목적지 피커용(별도 쿼리키로 캐시 오염 방지). */
  dest?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const childrenQuery = useQuery({
    queryKey: dest ? ["dest-folders", folder.id] : ["folders", folder.id],
    queryFn: () => (dest ? api.destFolders(folder.id) : api.folders(folder.id)),
    enabled: expanded,
  });
  const { isOver, setNodeRef } = useDroppable({
    id: `folder:${folder.id}`,
    disabled: !droppable,
  });
  const children = childrenQuery.data?.folders ?? [];

  // Spring-loaded: dragging over a collapsed node auto-expands it so nested
  // targets are reachable without dropping first (isOver is drag-only).
  useEffect(() => {
    if (!isOver || expanded) return;
    const t = window.setTimeout(() => setExpanded(true), SPRING_MS);
    return () => window.clearTimeout(t);
  }, [isOver, expanded]);

  return (
    <div>
      <div
        ref={droppable ? setNodeRef : undefined}
        className={`flex items-center gap-0.5 rounded-lg pr-2 text-sm transition-colors ${
          isOver
            ? "bg-blue-100 text-blue-800 ring-2 ring-blue-400"
            : selectedId === folder.id
              ? "bg-slate-200 font-medium text-slate-800"
              : "text-slate-700 hover:bg-slate-100"
        }`}
        style={{ paddingLeft: 4 }}
      >
        <button
          onClick={() => setExpanded((v) => !v)}
          aria-label={expanded ? "접기" : "펼치기"}
          className="flex h-5 w-5 shrink-0 items-center justify-center text-xs text-slate-400 hover:text-slate-700"
        >
          {expanded ? "▾" : "▸"}
        </button>
        <button
          onClick={() => onSelect?.(folder)}
          className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left"
        >
          <span aria-hidden>📁</span>
          <span className="truncate">{folderBasename(folder.name)}</span>
        </button>
      </div>
      {expanded && (
        <div style={{ paddingLeft: 12 }}>
          {childrenQuery.isPending && (
            <p className="py-1 pl-2 text-xs text-slate-400">불러오는 중…</p>
          )}
          {!childrenQuery.isPending && children.length === 0 && (
            <p className="py-1 pl-2 text-xs text-slate-300">(하위 폴더 없음)</p>
          )}
          {children.map((c) => (
            <FolderTreeNode
              key={c.id}
              folder={c}
              onSelect={onSelect}
              selectedId={selectedId}
              droppable={droppable}
              dest={dest}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Collapsible tree section for the side panels: the SELECTED library stays
 * open; the other one collapses to a header (still expandable — dragging
 * personal→team needs the team tree reachable, spec ch.4). */
export function TreeSection({
  label,
  defaultOpen,
  space,
  onSelect,
  selectedId,
  droppable = false,
}: {
  label: string;
  defaultOpen: boolean;
  space: Space;
  onSelect?: (f: PhotoFolder) => void;
  selectedId?: string;
  droppable?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  // Library switch re-decides which section is open.
  useEffect(() => setOpen(defaultOpen), [defaultOpen]);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-1 px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-600"
      >
        <span className="text-[9px]">{open ? "▾" : "▸"}</span>
        {label}
      </button>
      {open && (
        <FolderTree
          space={space}
          droppable={droppable}
          onSelect={onSelect}
          selectedId={selectedId}
        />
      )}
    </div>
  );
}

export function FolderTree({
  space,
  onSelect,
  selectedId,
  droppable = false,
  dest = false,
}: {
  space?: Space;
  onSelect?: (f: PhotoFolder) => void;
  selectedId?: string;
  droppable?: boolean;
  dest?: boolean;
}) {
  const topQuery = useQuery({
    queryKey: dest ? ["dest-folders", null] : ["folders", null],
    queryFn: () => (dest ? api.destFolders() : api.folders()),
  });
  const tops = (topQuery.data?.folders ?? []).filter(
    (f) => !space || f.space === space,
  );

  if (topQuery.isPending) {
    return <p className="px-2 py-2 text-sm text-slate-400">폴더 불러오는 중…</p>;
  }
  if (topQuery.isError) {
    return <p className="px-2 py-2 text-sm text-red-500">폴더를 불러오지 못했습니다.</p>;
  }
  return (
    <div>
      {tops.map((f) => (
        <FolderTreeNode
          key={f.id}
          folder={f}
          onSelect={onSelect}
          selectedId={selectedId}
          droppable={droppable}
          dest={dest}
        />
      ))}
    </div>
  );
}

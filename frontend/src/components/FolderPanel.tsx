import { useTimelineStore } from "../store/timeline";
import { useResizableWidth } from "../hooks/useResizableWidth";
import { FolderTree } from "./FolderTree";

/** Left folder panel for the timeline with two roles:
 * - drop target: drag photos onto a folder to move (⌥ = copy). Team folders
 *   are always shown — even while browsing the personal space — so
 *   personal→team moves are a plain drag (spec ch.4).
 * - navigation: clicking a folder opens it in the folder view.
 * Folders are a lazy tree (1500+ folders on the real NAS).
 */
export function FolderPanel() {
  const openFolderView = useTimelineStore((s) => s.openFolderView);
  const aside = useResizableWidth("nasphoto.timelineAsideWidth", 224);

  return (
    <>
      <aside
        data-no-boxselect
        style={{ width: aside.width }}
        className="hidden shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2 md:block"
      >
        <p className="px-2 pt-1 text-[11px] leading-snug text-slate-400">
          클릭하면 폴더 보기로 열기 · 사진을 끌어다 놓으면 이동 (⌥ 누르면 복사)
        </p>
        <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
          공용 폴더
        </h4>
        <FolderTree space="team" droppable onSelect={(f) => openFolderView([f])} />
        <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
          내 개인 폴더
        </h4>
        <FolderTree
          space="personal"
          droppable
          onSelect={(f) => openFolderView([f])}
        />
      </aside>
      <div
        {...aside.handleProps}
        className="hidden w-1 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-blue-300 active:bg-blue-400 md:block"
      />
    </>
  );
}

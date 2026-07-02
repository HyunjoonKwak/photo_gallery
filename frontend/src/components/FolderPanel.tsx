import { FolderTree } from "./FolderTree";

/** Left drop-target panel for the timeline. Team folders are always shown —
 * even while browsing the personal space — so personal→team moves are a plain
 * drag (spec ch.4). Folders are a lazy tree (1500+ folders on the real NAS).
 */
export function FolderPanel() {
  return (
    <aside
      data-no-boxselect
      className="hidden w-56 shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2 md:block"
    >
      <p className="px-2 pt-1 text-[11px] leading-snug text-slate-400">
        사진을 끌어다 놓으면 이동 (⌥ 누르면 복사)
      </p>
      <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
        공용 폴더
      </h4>
      <FolderTree space="team" droppable />
      <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
        내 개인 폴더
      </h4>
      <FolderTree space="personal" droppable />
    </aside>
  );
}

import { useTimelineStore } from "../store/timeline";
import { useResizableWidth } from "../hooks/useResizableWidth";
import { TreeSection } from "./FolderTree";

/** Left folder panel for the timeline with two roles:
 * - drop target: drag photos onto a folder to move (⌥ = copy). Team folders
 *   are always shown — even while browsing the personal space — so
 *   personal→team moves are a plain drag (spec ch.4).
 * - navigation: clicking a folder opens it in the folder view.
 * Folders are a lazy tree (1500+ folders on the real NAS).
 */
export function FolderPanel() {
  const openFolderView = useTimelineStore((s) => s.openFolderView);
  const space = useTimelineStore((s) => s.space);
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const aside = useResizableWidth("nasphoto.timelineAsideWidth", 224);
  // 선택 라이브러리의 트리만 펼치고, 반대쪽은 접힌 헤더로(펼치면 드롭 가능
  // — 개인→공용 드래그 이동은 스펙 핵심이라 접근은 유지).
  const personalOpen = viewedOwner != null || space === "personal";
  const sections = [
    {
      space: "team" as const,
      label: "가족 폴더",
      open: !personalOpen,
    },
    {
      space: "personal" as const,
      label: viewedOwner ? `${viewedOwner}의 개인 폴더` : "내 개인 폴더",
      open: personalOpen,
    },
  ].sort((a, b) => Number(b.open) - Number(a.open));

  return (
    <>
      <aside
        data-no-boxselect
        style={{ width: aside.width }}
        className="scroll-thin hidden shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2 md:block"
      >
        <p className="px-2 pt-1 text-[11px] leading-snug text-slate-400">
          클릭하면 폴더 보기로 열기 · 사진을 끌어다 놓으면 이동 (⌥ 누르면 복사)
        </p>
        {sections.map((s) => (
          <TreeSection
            key={s.space}
            space={s.space}
            label={s.label}
            defaultOpen={s.open}
            droppable
            onSelect={(f) => openFolderView([f])}
          />
        ))}
      </aside>
      <div
        {...aside.handleProps}
        className="hidden w-1 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-blue-300 active:bg-blue-400 md:block"
      />
    </>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useDroppable } from "@dnd-kit/core";
import { api } from "../api/client";
import type { PhotoFolder } from "../api/types";

/** Left drop-target panel. Team folders are always visible — even while
 * browsing the personal space — so personal→team moves are a plain drag
 * (spec ch.4). Folder rows highlight while a drag hovers them.
 */
function FolderRow({ folder }: { folder: PhotoFolder }) {
  const { isOver, setNodeRef } = useDroppable({ id: `folder:${folder.id}` });
  return (
    <li
      ref={setNodeRef}
      className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors ${
        isOver
          ? "bg-blue-100 text-blue-800 ring-2 ring-blue-400"
          : "text-slate-700 hover:bg-slate-100"
      }`}
    >
      <span aria-hidden>📁</span>
      <span className="truncate">{folder.name}</span>
    </li>
  );
}

function FolderGroup({ title, folders }: { title: string; folders: PhotoFolder[] }) {
  return (
    <div>
      <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h4>
      <ul className="space-y-0.5">
        {folders.map((f) => (
          <FolderRow key={f.id} folder={f} />
        ))}
      </ul>
    </div>
  );
}

export function FolderPanel() {
  const query = useQuery({ queryKey: ["folders"], queryFn: api.folders });
  const folders = query.data?.folders ?? [];
  const team = folders.filter((f) => f.space === "team");
  const personal = folders.filter((f) => f.space === "personal");

  return (
    <aside
      data-no-boxselect
      className="hidden w-52 shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2 md:block"
    >
      <p className="px-2 pt-1 text-[11px] leading-snug text-slate-400">
        사진을 끌어다 놓으면 이동 (⌥ 누르면 복사)
      </p>
      {query.isPending && <p className="px-2 py-3 text-sm text-slate-400">폴더 불러오는 중…</p>}
      {query.isError && (
        <p className="px-2 py-3 text-sm text-red-500">폴더를 불러오지 못했습니다.</p>
      )}
      <FolderGroup title="공용 폴더" folders={team} />
      <FolderGroup title="내 개인 폴더" folders={personal} />
    </aside>
  );
}

import { useState } from "react";
import type { PhotoFolder } from "../../api/types";
import { FolderTree } from "../FolderTree";

export type PickerMode = "move" | "copy" | "toTeam";

/** Destination picker for 이동/복사/공용으로 보내기.
 * "공용으로 보내기" defaults to copy — families usually want the personal
 * original kept (spec ch.4) — with a move/copy toggle to override.
 */
export function FolderPickerDialog({
  mode,
  count,
  onConfirm,
  onClose,
}: {
  mode: PickerMode;
  count: number;
  onConfirm: (folder: PhotoFolder, copyMode: boolean) => void;
  onClose: () => void;
}) {
  const [copyMode, setCopyMode] = useState(mode !== "move");
  const [selected, setSelected] = useState<PhotoFolder | null>(null);

  const title =
    mode === "toTeam"
      ? `${count}장 공용으로 보내기`
      : mode === "copy"
        ? `${count}장 복사`
        : `${count}장 이동`;

  return (
    <div
      data-no-boxselect
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-80 rounded-2xl bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-sm font-bold text-slate-800">{title}</h3>
        {selected && (
          <p className="mt-1 truncate text-xs text-blue-700">
            선택됨: {selected.name}
          </p>
        )}
        <div className="mt-1 max-h-72 overflow-y-auto">
          <h4 className="px-1 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            공용 폴더
          </h4>
          <FolderTree space="team" onSelect={setSelected} selectedId={selected?.id} />
          {mode !== "toTeam" && (
            <>
              <h4 className="px-1 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                내 개인 폴더
              </h4>
              <FolderTree
                space="personal"
                onSelect={setSelected}
                selectedId={selected?.id}
              />
            </>
          )}
        </div>

        {mode === "toTeam" && (
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={copyMode}
              onChange={(e) => setCopyMode(e.target.checked)}
            />
            원본을 개인 폴더에 남기기 (복사)
          </label>
        )}

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
          >
            취소
          </button>
          <button
            disabled={!selected}
            onClick={() => {
              if (selected) {
                onConfirm(selected, mode === "copy" ? true : copyMode && mode === "toTeam");
              }
            }}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            {mode === "copy" ? "복사" : mode === "toTeam" && copyMode ? "복사" : "이동"}
          </button>
        </div>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { PhotoFolder } from "../../api/types";

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
  const foldersQuery = useQuery({ queryKey: ["folders"], queryFn: api.folders });
  const [copyMode, setCopyMode] = useState(mode !== "move");
  const [selected, setSelected] = useState<PhotoFolder | null>(null);

  const all = foldersQuery.data?.folders ?? [];
  const folders = mode === "toTeam" ? all.filter((f) => f.space === "team") : all;
  const team = folders.filter((f) => f.space === "team");
  const personal = folders.filter((f) => f.space === "personal");

  const title =
    mode === "toTeam"
      ? `${count}장 공용으로 보내기`
      : mode === "copy"
        ? `${count}장 복사`
        : `${count}장 이동`;

  const group = (label: string, list: PhotoFolder[]) =>
    list.length > 0 && (
      <div key={label}>
        <h4 className="px-1 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
          {label}
        </h4>
        <ul className="space-y-0.5">
          {list.map((f) => (
            <li key={f.id}>
              <button
                onClick={() => setSelected(f)}
                className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ${
                  selected?.id === f.id
                    ? "bg-blue-100 text-blue-800 ring-1 ring-blue-300"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span aria-hidden>📁</span>
                <span className="truncate">{f.name}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );

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
        <div className="mt-1 max-h-72 overflow-y-auto">
          {group("공용 폴더", team)}
          {group("내 개인 폴더", personal)}
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

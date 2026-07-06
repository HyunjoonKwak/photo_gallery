import { useMemo, useState } from "react";
import type { PhotoFolder } from "../../api/types";
import { recentFolders, rememberFolder } from "../../lib/recentFolders";
import { FolderTree, folderBasename } from "../FolderTree";

export type PickerMode = "move" | "copy" | "toTeam" | "toPersonal";

/** Destination picker for 이동/복사/공용으로 보내기/2차로 보내기.
 * "공용으로 보내기"는 복사 기본(원본을 개인에 남김, spec ch.4). "2차로 보내기"
 * (1차 구역→개인 Photos)는 이동 기본. 둘 다 토글로 뒤집을 수 있다.
 * ``toPersonal``은 현재 스코프(zone)를 붙이지 않는 목적지 트리(개인/공용 Photos)를
 * 보여준다 — 소스는 zone이어도 목적지는 Photos 안이라야 한다.
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
  const copyable = mode === "toTeam" || mode === "toPersonal";
  const [copyMode, setCopyMode] = useState(mode === "copy" || mode === "toTeam");
  const [selected, setSelected] = useState<PhotoFolder | null>(null);
  const isDest = mode === "toPersonal"; // 스코프 미부착 목적지 트리
  // Recent destinations — 반복 정리 시 트리 탐색 없이 원클릭 선택.
  const recents = useMemo(
    () =>
      recentFolders().filter((f) => mode !== "toTeam" || f.space === "team"),
    [mode],
  );

  const title =
    mode === "toTeam"
      ? `${count}장 공용으로 보내기`
      : mode === "toPersonal"
        ? `${count}장 내 사진(2차)으로`
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
        {recents.length > 0 && (
          <div className="mt-2">
            <h4 className="px-1 pb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
              최근 사용
            </h4>
            <div className="flex flex-wrap gap-1">
              {recents.map((f) => (
                <button
                  key={f.id}
                  onClick={() => setSelected(f)}
                  title={f.name}
                  className={`max-w-full truncate rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    selected?.id === f.id
                      ? "border-blue-400 bg-blue-50 text-blue-700"
                      : "border-slate-200 text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  📁 {folderBasename(f.name)}
                  <span className="ml-1 text-[10px] text-slate-400">
                    {f.space === "team" ? "공용" : "개인"}
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="mt-1 max-h-72 overflow-y-auto">
          <h4 className="px-1 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            공용 폴더
          </h4>
          <FolderTree
            space="team"
            onSelect={setSelected}
            selectedId={selected?.id}
            dest={isDest}
          />
          {mode !== "toTeam" && (
            <>
              <h4 className="px-1 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                내 개인 폴더
              </h4>
              <FolderTree
                space="personal"
                onSelect={setSelected}
                selectedId={selected?.id}
                dest={isDest}
              />
            </>
          )}
        </div>

        {copyable && (
          <label className="mt-3 flex items-center gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={copyMode}
              onChange={(e) => setCopyMode(e.target.checked)}
            />
            {mode === "toTeam"
              ? "원본을 개인 폴더에 남기기 (복사)"
              : "원본을 1차 구역에 남기기 (복사)"}
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
                rememberFolder(selected);
                onConfirm(selected, mode === "copy" ? true : copyMode && copyable);
              }
            }}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            {mode === "copy" || (copyable && copyMode) ? "복사" : "이동"}
          </button>
        </div>
      </div>
    </div>
  );
}

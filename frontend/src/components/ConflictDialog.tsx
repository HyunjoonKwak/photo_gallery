import type { ConflictItem, ConflictStrategy } from "../api/types";

/** Same-filename collision dialog for move/copy into a folder.
 *
 * Raised only when the pre-flight check finds ≥1 conflict. Offers the three
 * FileStation strategies (rename keeps both, skip leaves them, overwrite
 * replaces — and is destructive, so it's visually separated + red).
 */
export function ConflictDialog({
  conflicts,
  copyMode,
  onChoose,
  onCancel,
}: {
  conflicts: ConflictItem[];
  copyMode: boolean;
  onChoose: (strategy: ConflictStrategy) => void;
  onCancel: () => void;
}) {
  const verb = copyMode ? "복사" : "이동";
  const preview = conflicts.slice(0, 5);
  const rest = conflicts.length - preview.length;

  const opt =
    "w-full rounded-lg border px-3 py-2.5 text-left text-sm transition-colors";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl">
        <h4 className="text-sm font-bold text-slate-800">
          같은 이름의 사진 {conflicts.length}장
        </h4>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
          대상 폴더에 이미 같은 파일명이 있습니다. 어떻게 {verb}할까요?
        </p>

        <ul className="mt-2 max-h-24 overflow-y-auto rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {preview.map((c) => (
            <li key={c.item_id} className="truncate">
              {c.filename}
            </li>
          ))}
          {rest > 0 && <li className="text-slate-400">외 {rest}장…</li>}
        </ul>

        <div className="mt-4 space-y-2">
          <button
            onClick={() => onChoose("rename")}
            className={`${opt} border-blue-200 hover:bg-blue-50`}
          >
            <span className="font-semibold text-blue-700">
              이름 바꿔 둘 다 보관
            </span>
            <span className="mt-0.5 block text-xs text-slate-500">
              들어오는 사진에 <code>_1</code>을 붙여 {verb} (예: IMG_1.jpg)
            </span>
          </button>
          <button
            onClick={() => onChoose("skip")}
            className={`${opt} border-slate-200 hover:bg-slate-50`}
          >
            <span className="font-semibold text-slate-700">건너뛰기</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              겹치는 사진은 그대로 두고 나머지만 {verb}
            </span>
          </button>
          <button
            onClick={() => onChoose("overwrite")}
            className={`${opt} border-red-200 hover:bg-red-50`}
          >
            <span className="font-semibold text-red-600">덮어쓰기</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              기존 파일을 교체합니다 — <b>되돌릴 수 없습니다.</b>
            </span>
          </button>
        </div>

        <div className="mt-4 flex justify-end">
          <button
            onClick={onCancel}
            className="rounded-lg border border-slate-300 px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            취소
          </button>
        </div>
      </div>
    </div>
  );
}

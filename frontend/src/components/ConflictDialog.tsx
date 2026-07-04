import { useConflictStore, type ConflictKind } from "../store/conflict";

/** Same-name collision dialog for move/copy — files or folders. Raised only
 * when the backend answers 409 with the conflict list. rename keeps both, skip
 * leaves them; files also offer overwrite (destructive, red). Folders never
 * overwrite (replacing a whole subtree is too dangerous). */
function ConflictDialog({
  kind,
  names,
  copyMode,
  onChoose,
  onCancel,
}: {
  kind: ConflictKind;
  names: string[];
  copyMode: boolean;
  onChoose: (strategy: string) => void;
  onCancel: () => void;
}) {
  const verb = copyMode ? "복사" : "이동";
  const noun = kind === "folder" ? "폴더" : "사진";
  const preview = names.slice(0, 5);
  const rest = names.length - preview.length;

  const opt =
    "w-full rounded-lg border px-3 py-2.5 text-left text-sm transition-colors";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl">
        <h4 className="text-sm font-bold text-slate-800">
          같은 이름의 {noun} {names.length}
          {kind === "folder" ? "개" : "장"}
        </h4>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
          대상 {kind === "folder" ? "위치" : "폴더"}에 이미 같은 이름이 있습니다.
          어떻게 {verb}할까요?
        </p>

        <ul className="mt-2 max-h-24 overflow-y-auto rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500">
          {preview.map((n) => (
            <li key={n} className="truncate">
              {n}
            </li>
          ))}
          {rest > 0 && <li className="text-slate-400">외 {rest}개…</li>}
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
              들어오는 {noun}에 <code>_1</code>을 붙여 {verb}
            </span>
          </button>
          <button
            onClick={() => onChoose("skip")}
            className={`${opt} border-slate-200 hover:bg-slate-50`}
          >
            <span className="font-semibold text-slate-700">건너뛰기</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              겹치는 {noun}은 그대로 두고 나머지만 {verb}
            </span>
          </button>
          {kind === "file" && (
            <button
              onClick={() => onChoose("overwrite")}
              className={`${opt} border-red-200 hover:bg-red-50`}
            >
              <span className="font-semibold text-red-600">덮어쓰기</span>
              <span className="mt-0.5 block text-xs text-slate-500">
                기존 파일을 교체합니다 — <b>되돌릴 수 없습니다.</b>
              </span>
            </button>
          )}
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

/** App-root host: renders the conflict dialog whenever any move/copy hits a
 * name collision (the backend 409 populates the store from useFileOps). */
export function ConflictDialogHost() {
  const pending = useConflictStore((s) => s.pending);
  const clear = useConflictStore((s) => s.clear);
  if (!pending) return null;
  return (
    <ConflictDialog
      kind={pending.kind}
      names={pending.names}
      copyMode={pending.copyMode}
      onChoose={(strategy) => {
        pending.onChoose(strategy);
        clear();
      }}
      onCancel={clear}
    />
  );
}

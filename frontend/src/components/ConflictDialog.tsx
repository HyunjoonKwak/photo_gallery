import { useConflictStore, type ConflictKind } from "../store/conflict";

const OPT =
  "w-full rounded-lg border px-3 py-2.5 text-left text-sm transition-colors";

/** Folder collision where every source folder is already fully contained in
 * its destination twin (완전 일치): 이동이면 원본 삭제 제안, 복사면 "동일" 안내. */
function FullMatchFolderDialog({
  names,
  copyMode,
  onChoose,
  onCancel,
}: {
  names: string[];
  copyMode: boolean;
  onChoose: (strategy: string) => void;
  onCancel: () => void;
}) {
  const label =
    names.length === 1
      ? `'${names[0]}'`
      : `'${names[0]}' 외 ${names.length - 1}개`;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl">
        <h4 className="text-sm font-bold text-slate-800">
          내용이 이미 대상과 완전히 같습니다
        </h4>
        <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
          {label} 폴더의 사진·하위 폴더가 대상에 <b>모두 그대로 있습니다.</b>
          {copyMode
            ? " 복사할 것이 없습니다."
            : " 원본 폴더를 어떻게 할까요?"}
        </p>

        {copyMode ? (
          <div className="mt-4 flex justify-end">
            <button
              onClick={onCancel}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
            >
              확인
            </button>
          </div>
        ) : (
          <>
            <div className="mt-4 space-y-2">
              <button
                onClick={() => onChoose("purge_source")}
                className={`${OPT} border-red-200 hover:bg-red-50`}
              >
                <span className="font-semibold text-red-600">
                  원본 폴더 삭제 (휴지통)
                </span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  대상에 이미 다 있으니 원본을 정리합니다 —{" "}
                  <b>되돌리기로 복원 가능</b>
                </span>
              </button>
              <button
                onClick={onCancel}
                className={`${OPT} border-slate-200 hover:bg-slate-50`}
              >
                <span className="font-semibold text-slate-700">
                  그대로 두기
                </span>
                <span className="mt-0.5 block text-xs text-slate-500">
                  아무것도 하지 않고 원본을 유지합니다
                </span>
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Same-name collision dialog for move/copy — files or folders. Raised only
 * when the backend answers 409 with the conflict list. rename keeps both, skip
 * leaves them; files also offer overwrite (destructive, red). Folders never
 * overwrite (replacing a whole subtree is too dangerous) but offer merge —
 * fold the source folder's contents into the existing one (inner file clashes
 * keep the existing file). When every source folder is already fully contained
 * in its twin, a dedicated full-match dialog is shown instead. */
function ConflictDialog({
  kind,
  names,
  copyMode,
  folderExtras,
  onChoose,
  onCancel,
}: {
  kind: ConflictKind;
  names: string[];
  copyMode: boolean;
  folderExtras?: number[];
  onChoose: (strategy: string) => void;
  onCancel: () => void;
}) {
  // 폴더 충돌인데 모든 원본이 대상에 완전 포함(추가분 0) → 전용 다이얼로그.
  if (
    kind === "folder" &&
    folderExtras &&
    folderExtras.length > 0 &&
    folderExtras.every((e) => e === 0)
  ) {
    return (
      <FullMatchFolderDialog
        names={names}
        copyMode={copyMode}
        onChoose={onChoose}
        onCancel={onCancel}
      />
    );
  }

  const verb = copyMode ? "복사" : "이동";
  const noun = kind === "folder" ? "폴더" : "사진";
  const preview = names.slice(0, 5);
  const rest = names.length - preview.length;
  // 부분 차이(폴더): 대상에 없는 항목 수 합 — 합치기 설명에 노출.
  const totalExtra = folderExtras?.reduce((a, b) => a + b, 0);

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
          {kind === "folder" && (
            <button
              onClick={() => onChoose("merge")}
              className={`${OPT} border-emerald-200 hover:bg-emerald-50`}
            >
              <span className="font-semibold text-emerald-700">
                합치기 (대상에 없는 것만 {verb})
              </span>
              <span className="mt-0.5 block text-xs text-slate-500">
                {totalExtra != null && totalExtra > 0
                  ? `대상에 없는 항목 약 ${totalExtra}개만 ${verb}합니다 — 같은 파일명은 기존 것을 유지`
                  : `대상의 같은 이름 폴더 안으로 사진·하위 폴더를 ${verb} — 같은 파일명은 기존 것을 유지`}
              </span>
            </button>
          )}
          <button
            onClick={() => onChoose("rename")}
            className={`${OPT} border-blue-200 hover:bg-blue-50`}
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
            className={`${OPT} border-slate-200 hover:bg-slate-50`}
          >
            <span className="font-semibold text-slate-700">건너뛰기</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              겹치는 {noun}은 그대로 두고 나머지만 {verb}
            </span>
          </button>
          {kind === "file" && (
            <button
              onClick={() => onChoose("overwrite")}
              className={`${OPT} border-red-200 hover:bg-red-50`}
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
      folderExtras={pending.folderExtras}
      onChoose={(strategy) => {
        pending.onChoose(strategy);
        clear();
      }}
      onCancel={() => {
        pending.onCancel?.();
        clear();
      }}
    />
  );
}

import { useState } from "react";
import { useTimelineStore } from "../../store/timeline";
import { useFileOps } from "../../hooks/useFileOps";
import { FolderPickerDialog, type PickerMode } from "./FolderPickerDialog";

/** Bottom floating action bar, visible while anything is selected (spec 9.1).
 * Destructive actions run immediately — safety comes from trash + the undo
 * toast, not confirmation dialogs (IMPROVEMENTS B-6 / NN/g).
 */
export function SelectionActionBar() {
  const count = useTimelineStore((s) => s.selected.size);
  const clear = useTimelineStore((s) => s.clearSelection);
  const ops = useFileOps();
  const [picker, setPicker] = useState<PickerMode | null>(null);

  if (count === 0) return null;

  const selectedIds = () => [...useTimelineStore.getState().selected];

  const btn =
    "rounded-lg px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 transition-colors disabled:opacity-40";

  return (
    <>
      <div
        data-no-boxselect
        className="fixed bottom-4 left-1/2 z-40 flex -translate-x-1/2 items-center gap-1 rounded-2xl bg-slate-800 px-3 py-2 shadow-xl"
      >
        <button
          onClick={clear}
          aria-label="선택 해제"
          className="mr-1 flex h-7 w-7 items-center justify-center rounded-full text-slate-300 hover:bg-slate-700"
        >
          ✕
        </button>
        <span className="mr-2 text-sm font-semibold text-white">
          {count}장 선택됨
        </span>
        <button className={btn} disabled={ops.isBusy} onClick={() => setPicker("move")}>
          이동
        </button>
        <button className={btn} disabled={ops.isBusy} onClick={() => setPicker("copy")}>
          복사
        </button>
        <button
          className={btn}
          disabled={ops.isBusy}
          onClick={() => setPicker("toTeam")}
        >
          공용으로 보내기
        </button>
        <button
          className="rounded-lg px-3 py-1.5 text-sm text-red-300 hover:bg-red-900/40 disabled:opacity-40"
          disabled={ops.isBusy}
          onClick={() => ops.remove(selectedIds())}
        >
          삭제
        </button>
      </div>

      {picker && (
        <FolderPickerDialog
          mode={picker}
          count={count}
          onClose={() => setPicker(null)}
          onConfirm={(folder, copyMode) => {
            setPicker(null);
            ops.move(selectedIds(), folder, copyMode);
          }}
        />
      )}
    </>
  );
}

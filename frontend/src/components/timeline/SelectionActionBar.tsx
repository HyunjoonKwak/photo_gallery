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
  const activeZone = useTimelineStore((s) => s.activeZone);
  const ops = useFileOps();
  const [picker, setPicker] = useState<PickerMode | null>(null);

  if (count === 0) return null;

  const selectedIds = () => [...useTimelineStore.getState().selected];

  const btn =
    "rounded-lg px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 transition-colors disabled:opacity-40";

  return (
    <>
      {/* max-w + flex-wrap: 폰 폭에서도 화면 밖으로 넘치지 않게 줄바꿈.
       * 모바일은 하단 탭 바 위(bottom-16)에 뜬다. */}
      <div
        data-no-boxselect
        className="fixed bottom-16 left-1/2 z-40 flex max-w-[95vw] -translate-x-1/2 flex-wrap items-center justify-center gap-1 rounded-2xl bg-slate-800 px-3 py-2 shadow-xl md:bottom-4"
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
        {activeZone ? (
          // 1차 구역: 고른 사진을 개인 Photos(2차)로. 이동/복사는 피커 토글.
          <button
            className={`${btn} bg-indigo-500/30 text-indigo-100 hover:bg-indigo-500/50`}
            disabled={ops.isBusy}
            onClick={() => setPicker("toPersonal")}
          >
            2차로 보내기
          </button>
        ) : (
          <>
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
          </>
        )}
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
            ops.move(selectedIds(), folder.id, copyMode);
          }}
        />
      )}
    </>
  );
}

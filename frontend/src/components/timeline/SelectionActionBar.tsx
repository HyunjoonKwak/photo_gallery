import { useTimelineStore } from "../../store/timeline";
import { useToastStore } from "../../store/toast";

/** Bottom floating action bar, visible while anything is selected (spec 9.1).
 * Buttons are placeholders until the file-operation APIs land (next step) —
 * they explain themselves via toast instead of failing silently.
 */
export function SelectionActionBar() {
  const count = useTimelineStore((s) => s.selected.size);
  const clear = useTimelineStore((s) => s.clearSelection);
  const push = useToastStore((s) => s.push);

  if (count === 0) return null;

  const placeholder = (action: string) => () =>
    push(`${count}장 ${action} — 파일 작업 API는 다음 단계에서 연결됩니다.`);

  const btn =
    "rounded-lg px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-700 transition-colors";

  return (
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
      <button className={btn} onClick={placeholder("이동")}>
        이동
      </button>
      <button className={btn} onClick={placeholder("복사")}>
        복사
      </button>
      <button className={btn} onClick={placeholder("공용으로 보내기")}>
        공용으로 보내기
      </button>
      <button
        className="rounded-lg px-3 py-1.5 text-sm text-red-300 hover:bg-red-900/40"
        onClick={placeholder("삭제(휴지통)")}
      >
        삭제
      </button>
    </div>
  );
}

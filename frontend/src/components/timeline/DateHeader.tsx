import { useTimelineStore } from "../../store/timeline";
import { formatDayHeader } from "../../lib/dates";
import type { PhotoItem } from "../../api/types";

/** Day header with a select-all check.
 *
 * The all/some/none state is *derived* from the selection set on every render
 * (IMPROVEMENTS B-3: never a second source of truth — the Immich #17304
 * double-bookkeeping bug is impossible by construction).
 */
export function DateHeader({ day, items }: { day: string; items?: PhotoItem[] }) {
  const state = useTimelineStore((s) => {
    if (!items || items.length === 0) return "none" as const;
    let n = 0;
    for (const it of items) if (s.selected.has(it.id)) n++;
    if (n === 0) return "none" as const;
    return n === items.length ? ("all" as const) : ("some" as const);
  });

  const onToggleAll = () => {
    if (!items || items.length === 0) return;
    useTimelineStore.getState().setMany(
      items.map((i) => i.id),
      state !== "all",
    );
  };

  return (
    <div className="group flex h-12 items-end gap-2 pb-2">
      <button
        onClick={onToggleAll}
        disabled={!items || items.length === 0}
        aria-label="이 날짜 전체 선택"
        className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold transition-opacity disabled:cursor-default ${
          state === "all"
            ? "bg-blue-600 text-white opacity-100"
            : state === "some"
              ? "bg-blue-200 text-blue-700 opacity-100"
              : "bg-slate-200 text-slate-500 opacity-0 group-hover:opacity-100"
        }`}
      >
        {state === "some" ? "–" : "✓"}
      </button>
      <h3 className="text-sm font-semibold text-slate-700">
        {formatDayHeader(day)}
      </h3>
    </div>
  );
}

import { useState } from "react";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import type { PhotoFolder } from "../api/types";
import { FolderPane } from "./FolderPane";
import { FolderTree, folderBasename } from "./FolderTree";

/** Center action bar of the dual-pane mode: move/copy the active pane's
 * selection into the other pane's folder, or trash it. Buttons mirror the
 * drag-and-drop operations for keyboard/precision users (IMPROVEMENTS B-4/B-6
 * — immediate execution + undo toast, no confirmation).
 */
function DualActions({
  activePane,
  sourceCurrent,
  destCurrent,
}: {
  activePane: 0 | 1;
  sourceCurrent: PhotoFolder | null;
  destCurrent: PhotoFolder | null;
}) {
  const selected = useTimelineStore((s) => s.selected);
  const ops = useFileOps();
  const n = selected.size;
  const arrow = activePane === 0 ? "→" : "←";
  const sameFolder = destCurrent != null && destCurrent.id === sourceCurrent?.id;
  const canTransfer = n > 0 && destCurrent != null && !sameFolder && !ops.isBusy;
  const destName = destCurrent ? folderBasename(destCurrent.name) : "반대쪽 폴더";

  const btn =
    "flex flex-col items-center gap-0.5 rounded-lg px-2 py-2 text-[11px] font-medium transition-colors disabled:opacity-30 lg:w-full";

  return (
    <div
      data-no-boxselect
      className="flex shrink-0 items-center justify-center gap-1 border-y border-slate-200 bg-slate-50 px-2 py-1 lg:w-20 lg:flex-col lg:border-x lg:border-y-0 lg:py-4"
    >
      <span className="text-xs font-semibold text-slate-500">{n}장</span>
      <button
        onClick={() => ops.move([...selected], destCurrent!.id, false)}
        disabled={!canTransfer}
        title={destCurrent ? `${destName}(으)로 이동` : "반대쪽 페인에서 폴더를 여세요"}
        className={`${btn} text-slate-600 enabled:hover:bg-blue-100 enabled:hover:text-blue-700`}
      >
        <span className="text-base leading-none">{arrow}</span>
        이동
      </button>
      <button
        onClick={() => ops.move([...selected], destCurrent!.id, true)}
        disabled={!canTransfer}
        title={destCurrent ? `${destName}(으)로 복사` : "반대쪽 페인에서 폴더를 여세요"}
        className={`${btn} text-slate-600 enabled:hover:bg-blue-100 enabled:hover:text-blue-700`}
      >
        <span className="text-base leading-none">⧉</span>
        복사
      </button>
      <button
        onClick={() => ops.remove([...selected])}
        disabled={n === 0 || ops.isBusy}
        title="휴지통으로 이동 (되돌리기 가능)"
        className={`${btn} text-slate-600 enabled:hover:bg-red-100 enabled:hover:text-red-700`}
      >
        <span className="text-base leading-none">🗑</span>
        삭제
      </button>
    </div>
  );
}

/** Folder view (spec 9.3): Finder-style browsing with two layouts.
 * - 단일: lazy tree on the left + one drill-in pane.
 * - 분할: two independent panes side by side (commander pattern) — select in
 *   one, move/copy to the other via the center bar or drag-and-drop. The
 *   clicked pane is "active" and owns the global selection; the inactive
 *   pane's background is a drop target for its current folder.
 */
export function FolderView() {
  const [dual, setDual] = useState(false);
  const [pathA, setPathA] = useState<PhotoFolder[]>([]);
  const [pathB, setPathB] = useState<PhotoFolder[]>([]);
  const [activePane, setActivePane] = useState<0 | 1>(0);
  const ops = useFileOps();
  const clearSelection = useTimelineStore((s) => s.clearSelection);

  const currentA = pathA.length ? pathA[pathA.length - 1] : null;
  const currentB = pathB.length ? pathB[pathB.length - 1] : null;
  const activeCurrent = activePane === 0 ? currentA : currentB;
  const inactiveCurrent = activePane === 0 ? currentB : currentA;

  const activate = (pane: 0 | 1) => {
    if (pane !== activePane) {
      clearSelection();
      setActivePane(pane);
    }
  };

  const toggleDual = (on: boolean) => {
    if (on === dual) return;
    clearSelection();
    setActivePane(0);
    setDual(on);
  };

  const onCreateFolder = () => {
    const name = window.prompt("새 폴더 이름 (공용 최상위에 생성)");
    if (name?.trim()) ops.createFolder(activeCurrent?.space ?? "team", name.trim());
  };

  return (
    <div className="flex h-full flex-col">
      {/* View toolbar: single/dual layout switch */}
      <div
        data-no-boxselect
        className="flex shrink-0 items-center justify-end gap-2 border-b border-slate-200 bg-white px-4 py-1.5"
      >
        {dual && (
          <span className="mr-auto text-xs text-slate-400">
            한쪽에서 선택 → 가운데 버튼이나 드래그로 반대쪽 폴더로 이동/복사
          </span>
        )}
        <nav className="flex gap-1 rounded-lg bg-slate-100 p-0.5">
          <button
            onClick={() => toggleDual(false)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              !dual ? "bg-white text-slate-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            ▤ 단일
          </button>
          <button
            onClick={() => toggleDual(true)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
              dual ? "bg-white text-slate-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            ▥ 분할
          </button>
        </nav>
      </div>

      {!dual && (
        <div className="flex min-h-0 flex-1">
          {/* Left: quick-jump tree. Selecting resets the breadcrumb. */}
          <aside
            data-no-boxselect
            className="w-60 shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2"
          >
            <button
              onClick={onCreateFolder}
              className="mx-2 mt-1 mb-1 w-[calc(100%-1rem)] rounded-lg border border-dashed border-slate-300 px-2 py-1.5 text-sm text-slate-500 hover:border-slate-400 hover:text-slate-700"
            >
              + 새 폴더
            </button>
            <h4 className="px-2 pb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              공용
            </h4>
            <FolderTree
              space="team"
              droppable
              selectedId={currentA?.id}
              onSelect={(f) => setPathA([f])}
            />
            <h4 className="px-2 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
              개인
            </h4>
            <FolderTree
              space="personal"
              droppable
              selectedId={currentA?.id}
              onSelect={(f) => setPathA([f])}
            />
          </aside>
          <main className="flex min-w-0 flex-1">
            <FolderPane
              path={pathA}
              onPathChange={setPathA}
              active
              onActivate={() => {}}
              dndPrefix="s-"
            />
          </main>
        </div>
      )}

      {dual && (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <section
            className={`flex min-h-0 min-w-0 flex-1 ${
              activePane === 0 ? "" : "opacity-95"
            }`}
          >
            <FolderPane
              path={pathA}
              onPathChange={setPathA}
              active={activePane === 0}
              onActivate={() => activate(0)}
              dndPrefix="a-"
              dropTarget={activePane !== 0}
            />
          </section>
          <DualActions
            activePane={activePane}
            sourceCurrent={activeCurrent}
            destCurrent={inactiveCurrent}
          />
          <section
            className={`flex min-h-0 min-w-0 flex-1 ${
              activePane === 1 ? "" : "opacity-95"
            }`}
          >
            <FolderPane
              path={pathB}
              onPathChange={setPathB}
              active={activePane === 1}
              onActivate={() => activate(1)}
              dndPrefix="b-"
              dropTarget={activePane !== 1}
            />
          </section>
        </div>
      )}
    </div>
  );
}

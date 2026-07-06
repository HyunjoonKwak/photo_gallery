import { useEffect, useState } from "react";
import { useTimelineStore } from "../store/timeline";
import { useFileOps } from "../hooks/useFileOps";
import { useResizableWidth } from "../hooks/useResizableWidth";
import type { PhotoFolder } from "../api/types";
import { FolderPane } from "./FolderPane";
import { TreeSection, folderBasename } from "./FolderTree";

/** Center action bar of the dual-pane mode: move/copy the active pane's
 * selection into the other pane's folder, or trash it. Buttons mirror the
 * drag-and-drop operations for keyboard/precision users (IMPROVEMENTS B-4/B-6
 * — immediate execution + undo toast, no confirmation).
 */
function DualActions({
  activePane,
  sourceCurrent,
  destCurrent,
  folderSel,
  onFoldersDone,
}: {
  activePane: 0 | 1;
  sourceCurrent: PhotoFolder | null;
  destCurrent: PhotoFolder | null;
  /** 활성 페인에서 ✓ 체크된 폴더들 — 있으면 버튼이 폴더 모드로 동작. */
  folderSel: Map<string, PhotoFolder>;
  onFoldersDone: () => void;
}) {
  const selected = useTimelineStore((s) => s.selected);
  const ops = useFileOps();
  const n = selected.size;
  const nf = folderSel.size;
  const folderMode = nf > 0;
  const arrow = activePane === 0 ? "→" : "←";
  const sameFolder = destCurrent != null && destCurrent.id === sourceCurrent?.id;
  const canTransfer = folderMode
    ? destCurrent != null && !folderSel.has(destCurrent.id) && !ops.isBusy
    : n > 0 && destCurrent != null && !sameFolder && !ops.isBusy;
  const destName = destCurrent ? folderBasename(destCurrent.name) : "반대쪽 폴더";

  const transferFolders = (copy: boolean) => {
    const folders = [...folderSel.values()];
    ops.moveFolders(
      folders[0].space,
      folders.map((f) => f.id),
      destCurrent!.id,
      copy,
      onFoldersDone,
    );
  };

  // 사진 이동/복사: 충돌은 백엔드가 409로 알려 전역 다이얼로그가 처리한다
  // (ConflictDialogHost) — 여기선 그냥 이동을 호출한다.
  const transferPhotos = (copy: boolean) =>
    ops.move([...selected], destCurrent!.id, copy);

  const btn =
    "flex flex-col items-center gap-0.5 rounded-lg px-2 py-2 text-[11px] font-medium transition-colors disabled:opacity-30 lg:w-full";

  return (
    <div
      data-no-boxselect
      className="flex shrink-0 items-center justify-center gap-1 border-y border-slate-200 bg-slate-50 px-2 py-1 lg:w-20 lg:flex-col lg:border-x lg:border-y-0 lg:py-4"
    >
      <span className="text-xs font-semibold text-slate-500">
        {folderMode ? `📁${nf}개` : `${n}장`}
      </span>
      <button
        onClick={() => (folderMode ? transferFolders(false) : transferPhotos(false))}
        disabled={!canTransfer}
        title={
          destCurrent
            ? `${destName}(으)로 ${folderMode ? "폴더째 " : ""}이동`
            : "반대쪽 페인에서 폴더를 여세요"
        }
        className={`${btn} text-slate-600 enabled:hover:bg-blue-100 enabled:hover:text-blue-700`}
      >
        <span className="text-base leading-none">{arrow}</span>
        이동
      </button>
      <button
        onClick={() => (folderMode ? transferFolders(true) : transferPhotos(true))}
        disabled={!canTransfer}
        title={
          destCurrent
            ? `${destName}(으)로 ${folderMode ? "폴더째 " : ""}복사`
            : "반대쪽 페인에서 폴더를 여세요"
        }
        className={`${btn} text-slate-600 enabled:hover:bg-blue-100 enabled:hover:text-blue-700`}
      >
        <span className="text-base leading-none">⧉</span>
        복사
      </button>
      <button
        onClick={() => ops.remove([...selected])}
        disabled={folderMode || n === 0 || ops.isBusy}
        title={
          folderMode
            ? "폴더 삭제는 브레드크럼의 [폴더 삭제]로 (빈 폴더만)"
            : "휴지통으로 이동 (되돌리기 가능)"
        }
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
  const aside = useResizableWidth("nasphoto.folderAsideWidth", 240);
  const [pathA, setPathA] = useState<PhotoFolder[]>([]);
  const [pathB, setPathB] = useState<PhotoFolder[]>([]);
  const [activePane, setActivePane] = useState<0 | 1>(0);
  const clearSelection = useTimelineStore((s) => s.clearSelection);

  // 폴더째 이동/복사(분할 뷰): 활성 페인에서 ✓ 체크된 폴더들. 사진 선택과
  // 배타적 — 폴더를 체크하면 사진 선택을 비우고, 사진을 선택하면 여기가 비워짐.
  const [folderSel, setFolderSel] = useState<Map<string, PhotoFolder>>(
    new Map(),
  );
  const clearFolderSel = () => setFolderSel(new Map());
  const toggleFolderCheck = (f: PhotoFolder) => {
    setFolderSel((prev) => {
      const next = new Map(prev);
      if (next.has(f.id)) next.delete(f.id);
      else next.set(f.id, f);
      return next;
    });
    clearSelection();
  };
  const toggleAllFolders = (folders: PhotoFolder[], on: boolean) => {
    setFolderSel((prev) => {
      const next = new Map(prev);
      for (const f of folders) {
        if (on) next.set(f.id, f);
        else next.delete(f.id);
      }
      return next;
    });
    clearSelection(); // 폴더 선택은 사진 선택과 배타적
  };
  const photoSelCount = useTimelineStore((s) => s.selected.size);
  useEffect(() => {
    if (photoSelCount > 0) setFolderSel(new Map());
  }, [photoSelCount]);

  // 정리 대상 라이브러리가 바뀜(구성원 전환 또는 1차 구역 전환) → 옛 브레드크럼은
  // 이전 트리(경로형 id)를 가리키므로 루트로 리셋.
  const viewedOwner = useTimelineStore((s) => s.viewedOwner);
  const activeZone = useTimelineStore((s) => s.activeZone);
  const activeZoneId = activeZone?.id ?? null;
  useEffect(() => {
    setPathA([]);
    setPathB([]);
    setActivePane(0);
    setFolderSel(new Map());
  }, [viewedOwner, activeZoneId]);

  // Cross-view jump (e.g. timeline's folder panel): open the requested folder
  // in pane A and make it the active pane.
  const pendingPath = useTimelineStore((s) => s.pendingFolderPath);
  useEffect(() => {
    if (pendingPath) {
      setPathA(pendingPath);
      setActivePane(0);
      useTimelineStore.getState().consumePendingFolderPath();
    }
  }, [pendingPath]);

  const currentA = pathA.length ? pathA[pathA.length - 1] : null;
  const currentB = pathB.length ? pathB[pathB.length - 1] : null;
  const activeCurrent = activePane === 0 ? currentA : currentB;
  const inactiveCurrent = activePane === 0 ? currentB : currentA;

  const activate = (pane: 0 | 1) => {
    if (pane !== activePane) {
      clearSelection();
      setFolderSel(new Map());
      setActivePane(pane);
    }
  };

  const toggleDual = (on: boolean) => {
    if (on === dual) return;
    clearSelection();
    setFolderSel(new Map());
    setActivePane(0);
    setDual(on);
  };

  // 페인 내 이동(드릴인/브레드크럼)하면 체크된 폴더가 화면에서 사라지므로
  // 선택도 함께 해제 (사진 선택과 동일한 규칙).
  const changePathA = (p: PhotoFolder[]) => {
    setFolderSel(new Map());
    setPathA(p);
  };
  const changePathB = (p: PhotoFolder[]) => {
    setFolderSel(new Map());
    setPathB(p);
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
            사진 선택 또는 폴더 ✓ 체크 → 가운데 버튼이나 드래그로 반대쪽
            폴더로 이동/복사
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
          {/* Left: quick-jump tree — 모바일은 메인 페인 카드 탐색으로 충분해
           * 숨김 (390px에서 트리가 화면 60%를 차지하던 문제). */}
          <aside
            data-no-boxselect
            style={{ width: aside.width }}
            className="hidden shrink-0 overflow-y-auto border-r border-slate-200 bg-white px-2 py-2 md:block"
          >
            {/* 새 폴더/삭제는 우측 페인 브레드크럼으로 통합(단일·분할 공용) */}
            {/* 1차 구역은 zone 트리만(공용/개인 Foto 없음); 그 외엔 선택 라이브러리
             * 트리를 펼치고 반대쪽은 접힌 헤더 */}
            {(activeZone
              ? (["personal"] as const)
              : viewedOwner || useTimelineStore.getState().space === "personal"
                ? (["personal", "team"] as const)
                : (["team", "personal"] as const)
            ).map((sp, i) => (
              <TreeSection
                key={sp}
                space={sp}
                label={
                  activeZone
                    ? activeZone.label
                    : sp === "team"
                      ? "공용"
                      : viewedOwner
                        ? `${viewedOwner}의 개인`
                        : "개인"
                }
                defaultOpen={i === 0}
                droppable
                selectedId={currentA?.id}
                onSelect={(f) => setPathA([f])}
              />
            ))}
          </aside>
          <div
            {...aside.handleProps}
            className="hidden w-1 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-blue-300 active:bg-blue-400 md:block"
          />
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
              onPathChange={changePathA}
              active={activePane === 0}
              onActivate={() => activate(0)}
              dndPrefix="a-"
              dropTarget={activePane !== 0}
              checkedFolderIds={new Set(folderSel.keys())}
              onToggleFolderCheck={toggleFolderCheck}
              onToggleAllFolders={toggleAllFolders}
            />
          </section>
          <DualActions
            activePane={activePane}
            sourceCurrent={activeCurrent}
            destCurrent={inactiveCurrent}
            folderSel={folderSel}
            onFoldersDone={clearFolderSel}
          />
          <section
            className={`flex min-h-0 min-w-0 flex-1 ${
              activePane === 1 ? "" : "opacity-95"
            }`}
          >
            <FolderPane
              path={pathB}
              onPathChange={changePathB}
              active={activePane === 1}
              onActivate={() => activate(1)}
              dndPrefix="b-"
              dropTarget={activePane !== 1}
              checkedFolderIds={new Set(folderSel.keys())}
              onToggleFolderCheck={toggleFolderCheck}
              onToggleAllFolders={toggleAllFolders}
            />
          </section>
        </div>
      )}
    </div>
  );
}

/** File-operation mutations with the full post-op UX (IMPROVEMENTS B-3/B-6):
 * selection auto-clears, affected timeline days invalidate precisely, and an
 * action toast offers 되돌리기 (which itself invalidates + confirms).
 * No confirmation dialogs — destructive ops are reversible via trash + undo.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type {
  ConflictStrategy,
  EmptiedFolder,
  MoveFoldersRequest,
  OperationResponse,
  Space,
} from "../api/types";
import { useConflictStore, conflictInfoOf } from "../store/conflict";
import { useProgressStore } from "../store/progress";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";

/** crypto.randomUUID is secure-context only — plain-HTTP NAS access
 * (http://<nas-ip>:9800) doesn't have it, so fall back to a manual key. */
function genProgressKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `p-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Start count-based progress tracking for one bulk mutation (B-6): create a
 * key the backend reports against, poll it while the request runs, and hand
 * back `stop` for the mutation's onSettled. */
function startProgress(label: string) {
  const key = genProgressKey();
  const store = useProgressStore.getState();
  store.start(key, label);
  const timer = window.setInterval(() => {
    api
      .opProgress(key)
      .then((r) => {
        if (r.active) {
          useProgressStore.getState().patch(key, r.done, r.total, r.label);
        }
      })
      .catch(() => {
        // polling is best-effort; the bar just stops updating
      });
  }, 700);
  return {
    key,
    stop: () => {
      window.clearInterval(timer);
      useProgressStore.getState().clear(key);
    },
  };
}

export function useFileOps() {
  const queryClient = useQueryClient();

  // 폴더 이동/삭제는 파일시스템엔 즉시 반영되지만 Synology Photos 인덱스가
  // 새 위치를 재색인할 때까지 옮긴 폴더가 목록에 안 나타난다(인덱스 지연,
  // 2026-07-04 실 NAS 보고). 즉시 무효화는 옛 인덱스를 다시 읽을 뿐이라,
  // 재색인이 따라잡을 시간을 두고 몇 차례 더 무효화해 자동으로 나타나게 한다.
  const RESETTLE_MS = [1500, 4000, 8000];
  const resettleFolders = () => {
    for (const ms of RESETTLE_MS) {
      window.setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["folders"] });
        queryClient.invalidateQueries({ queryKey: ["folder-counts"] });
        // 폴더 뷰 사진 목록도 재색인이 따라잡는 대로 갱신 — 이동/삭제한 사진이
        // 옛 위치에 남거나 새 위치에 늦게 뜨는 인덱스 지연을 수렴시킨다.
        queryClient.invalidateQueries({ queryKey: ["folder-items"] });
      }, ms);
    }
  };

  const invalidateAffected = (res: OperationResponse) => {
    // Buckets (counts changed) + only the touched day buckets + folder views.
    queryClient.invalidateQueries({ queryKey: ["buckets"] });
    for (const a of res.affected) {
      queryClient.invalidateQueries({ queryKey: ["bucket", a.space, a.day] });
    }
    queryClient.invalidateQueries({ queryKey: ["folder-items"] });
    queryClient.invalidateQueries({ queryKey: ["folder-counts"] });
    queryClient.invalidateQueries({ queryKey: ["ops"] });
    queryClient.invalidateQueries({ queryKey: ["dedup-groups"] });
  };

  const undoMutation = useMutation({
    mutationFn: (vars: { opId: number; progressKey?: string }) =>
      api.undoOp(vars.opId, vars.progressKey),
    onSuccess: (res) => {
      invalidateAffected(res);
      useToastStore.getState().push(res.summary);
    },
    onError: (err) => useToastStore.getState().push((err as Error).message),
  });

  const runUndo = (opId: number) => {
    const p = startProgress("되돌리기");
    undoMutation.mutate({ opId, progressKey: p.key }, { onSettled: p.stop });
  };

  // Move away all of a folder's photos and it's left empty — offer to clean it
  // up (사용자 결정: 자동 삭제 대신 정리 제안 토스트). Runs the same rmdir path,
  // which refuses non-empty folders, so a late-arriving file is never lost.
  const cleanupEmptied = (folders: EmptiedFolder[]) => {
    for (const f of folders) {
      rmdirMutation.mutate({
        space: f.space,
        folder_id: f.folder_id,
        target_user: targetUser(),
      });
    }
  };

  const offerCleanup = (res: OperationResponse) => {
    const emptied = res.emptied_folders ?? [];
    if (emptied.length === 0) return;
    const label =
      emptied.length === 1
        ? `'${emptied[0].name}'`
        : `'${emptied[0].name}' 외 ${emptied.length - 1}개`;
    useToastStore.getState().push(`${label} 폴더가 비었습니다`, {
      label: "빈 폴더 정리",
      run: () => cleanupEmptied(emptied),
    });
  };

  const afterOperation = (res: OperationResponse) => {
    useTimelineStore.getState().clearSelection();
    invalidateAffected(res);
    useToastStore.getState().push(
      `${res.summary}했습니다`,
      res.undoable
        ? { label: "되돌리기", run: () => runUndo(res.operation_id) }
        : undefined,
    );
    offerCleanup(res);
    // 폴더 뷰에서의 이동/삭제는 Photos 재색인 지연으로 옛 위치에 남을 수 있어,
    // 서버 tombstone(즉시 숨김) + 지연 재조회(새 위치 반영)로 함께 수렴시킨다.
    resettleFolders();
  };

  const onError = (err: unknown) =>
    useToastStore.getState().push((err as Error).message);

  const moveMutation = useMutation({
    mutationFn: api.opMove,
    onSuccess: afterOperation,
    // Filename collisions come back as 409+conflict list: raise the 처리 방법
    // dialog (globally, so drag-drop/액션바/라이트박스 이동 모두 커버) and retry
    // with the chosen strategy. Everything else is a plain error toast.
    onError: (err, variables) => {
      const info = conflictInfoOf(err);
      if (!info) return onError(err);
      useConflictStore.getState().ask({
        kind: info.kind,
        names: info.names,
        copyMode: variables.copy_mode,
        onChoose: (strategy) => {
          const p = startProgress(variables.copy_mode ? "복사" : "이동");
          moveMutation.mutate(
            {
              ...variables,
              conflict_strategy: strategy as ConflictStrategy,
              progress_key: p.key,
            },
            { onSettled: p.stop },
          );
        },
      });
    },
  });
  const deleteMutation = useMutation({
    mutationFn: api.opDelete,
    onSuccess: afterOperation,
    onError,
  });
  const mkdirMutation = useMutation({
    mutationFn: api.createFolder,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["folders"] });
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      resettleFolders(); // 최상위 생성(FileStation)은 재색인 지연이 있어 지연 재조회
      useToastStore.getState().push(
        `${res.summary}했습니다`,
        res.undoable
          ? {
              label: "되돌리기",
              // mkdir undo is a single folder removal — no progress needed
              run: () => undoMutation.mutate({ opId: res.operation_id }),
            }
          : undefined,
      );
    },
    onError,
  });

  const moveFoldersMutation = useMutation({
    mutationFn: api.moveFolders,
    onSuccess: (res) => {
      // 폴더 구조가 통째로 바뀜 — 폴더/사진 캐시 광범위 무효화.
      queryClient.invalidateQueries({ queryKey: ["folders"] });
      queryClient.invalidateQueries({ queryKey: ["folder-items"] });
      queryClient.invalidateQueries({ queryKey: ["folder-counts"] });
      queryClient.invalidateQueries({ queryKey: ["buckets"] });
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      resettleFolders(); // 옮긴 폴더가 대상 위치에 재색인되는 대로 나타나게
      useToastStore.getState().push(
        `${res.summary}했습니다`,
        res.undoable
          ? { label: "되돌리기", run: () => runUndo(res.operation_id) }
          : undefined,
      );
    },
    // 대상에 같은 이름 폴더가 있으면 409 → 전역 다이얼로그(폴더 옵션: 이름변경/
    // 건너뛰기), 선택 전략으로 재시도. 조용히 건너뛰던 문제 해결(2026-07-05).
    onError: (err, variables) => {
      const info = conflictInfoOf(err);
      if (!info) return onError(err);
      useConflictStore.getState().ask({
        kind: info.kind,
        names: info.names,
        copyMode: variables.copy_mode,
        onChoose: (strategy) => {
          const p = startProgress(variables.copy_mode ? "폴더 복사" : "폴더 이동");
          moveFoldersMutation.mutate(
            {
              ...variables,
              conflict_strategy: strategy as MoveFoldersRequest["conflict_strategy"],
              progress_key: p.key,
            },
            { onSettled: p.stop },
          );
        },
      });
    },
  });

  const rmdirMutation = useMutation({
    mutationFn: api.removeFolder,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["folders"] });
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      // 재귀 삭제(trash_folder)는 사진까지 빠지므로 사진 캐시도 무효화.
      queryClient.invalidateQueries({ queryKey: ["folder-items"] });
      queryClient.invalidateQueries({ queryKey: ["folder-counts"] });
      queryClient.invalidateQueries({ queryKey: ["buckets"] });
      resettleFolders(); // 삭제 반영이 인덱스에 늦게 잡혀도 결국 수렴하게
      useToastStore.getState().push(
        `${res.summary}했습니다`,
        res.undoable
          ? { label: "되돌리기", run: () => runUndo(res.operation_id) }
          : undefined,
      );
    },
    onError,
  });

  const targetUser = () => useTimelineStore.getState().viewedOwner ?? undefined;
  // Source space: prefer the items' own space (folder view can operate on
  // personal-folder photos while the global scope is team), else the scope.
  const spaceOf = (itemIds: string[]) => {
    const s = useTimelineStore.getState();
    for (const id of itemIds) {
      const sp = s.itemsById.get(id)?.space;
      if (sp) return sp;
    }
    return s.space;
  };

  return {
    move: (
      itemIds: string[],
      folderId: string,
      copyMode: boolean,
      conflictStrategy?: ConflictStrategy,
    ) => {
      const p = startProgress(copyMode ? "복사" : "이동");
      moveMutation.mutate(
        {
          space: spaceOf(itemIds),
          item_ids: itemIds,
          dest_folder_id: folderId,
          copy_mode: copyMode,
          conflict_strategy: conflictStrategy,
          target_user: targetUser(),
          progress_key: p.key,
        },
        { onSettled: p.stop },
      );
    },
    remove: (itemIds: string[], onSuccess?: () => void) => {
      const p = startProgress("삭제");
      deleteMutation.mutate(
        {
          space: spaceOf(itemIds),
          item_ids: itemIds,
          target_user: targetUser(),
          progress_key: p.key,
        },
        { onSuccess: () => onSuccess?.(), onSettled: p.stop },
      );
    },
    createFolder: (space: Space, name: string, parentId?: string) =>
      mkdirMutation.mutate({
        space,
        name,
        parent_id: parentId,
        target_user: targetUser(),
      }),
    moveFolders: (
      space: Space,
      folderIds: string[],
      destFolderId: string,
      copyMode: boolean,
      onSuccess?: () => void,
    ) => {
      const p = startProgress(copyMode ? "폴더 복사" : "폴더 이동");
      moveFoldersMutation.mutate(
        {
          space,
          folder_ids: folderIds,
          dest_folder_id: destFolderId,
          copy_mode: copyMode,
          target_user: targetUser(),
          progress_key: p.key,
        },
        { onSuccess: () => onSuccess?.(), onSettled: p.stop },
      );
    },
    removeFolder: (
      space: Space,
      folderId: string,
      recursive: boolean,
      onSuccess?: () => void,
    ) =>
      rmdirMutation.mutate(
        { space, folder_id: folderId, recursive, target_user: targetUser() },
        { onSuccess: () => onSuccess?.() },
      ),
    undo: runUndo,
    isBusy:
      moveMutation.isPending ||
      deleteMutation.isPending ||
      mkdirMutation.isPending ||
      moveFoldersMutation.isPending ||
      rmdirMutation.isPending,
  };
}

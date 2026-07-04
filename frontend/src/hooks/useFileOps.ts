/** File-operation mutations with the full post-op UX (IMPROVEMENTS B-3/B-6):
 * selection auto-clears, affected timeline days invalidate precisely, and an
 * action toast offers 되돌리기 (which itself invalidates + confirms).
 * No confirmation dialogs — destructive ops are reversible via trash + undo.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { OperationResponse, Space } from "../api/types";
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

  const afterOperation = (res: OperationResponse) => {
    useTimelineStore.getState().clearSelection();
    invalidateAffected(res);
    useToastStore.getState().push(
      `${res.summary}했습니다`,
      res.undoable
        ? { label: "되돌리기", run: () => runUndo(res.operation_id) }
        : undefined,
    );
  };

  const onError = (err: unknown) =>
    useToastStore.getState().push((err as Error).message);

  const moveMutation = useMutation({
    mutationFn: api.opMove,
    onSuccess: afterOperation,
    onError,
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
      useToastStore.getState().push(
        `${res.summary}했습니다`,
        res.undoable
          ? { label: "되돌리기", run: () => runUndo(res.operation_id) }
          : undefined,
      );
    },
    onError,
  });

  const rmdirMutation = useMutation({
    mutationFn: api.removeFolder,
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ["folders"] });
      queryClient.invalidateQueries({ queryKey: ["ops"] });
      useToastStore.getState().push(`${res.summary}했습니다`);
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
    move: (itemIds: string[], folderId: string, copyMode: boolean) => {
      const p = startProgress(copyMode ? "복사" : "이동");
      moveMutation.mutate(
        {
          space: spaceOf(itemIds),
          item_ids: itemIds,
          dest_folder_id: folderId,
          copy_mode: copyMode,
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
    removeFolder: (space: Space, folderId: string, onSuccess?: () => void) =>
      rmdirMutation.mutate(
        { space, folder_id: folderId, target_user: targetUser() },
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

/** File-operation mutations with the full post-op UX (IMPROVEMENTS B-3/B-6):
 * selection auto-clears, affected timeline days invalidate precisely, and an
 * action toast offers 되돌리기 (which itself invalidates + confirms).
 * No confirmation dialogs — destructive ops are reversible via trash + undo.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { OperationResponse, Space } from "../api/types";
import { useTimelineStore } from "../store/timeline";
import { useToastStore } from "../store/toast";

export function useFileOps() {
  const queryClient = useQueryClient();

  const invalidateAffected = (res: OperationResponse) => {
    // Buckets (counts changed) + only the touched day buckets + folder views.
    queryClient.invalidateQueries({ queryKey: ["buckets"] });
    for (const a of res.affected) {
      queryClient.invalidateQueries({ queryKey: ["bucket", a.space, a.day] });
    }
    queryClient.invalidateQueries({ queryKey: ["folder-items"] });
    queryClient.invalidateQueries({ queryKey: ["ops"] });
    queryClient.invalidateQueries({ queryKey: ["dedup-groups"] });
  };

  const undoMutation = useMutation({
    mutationFn: api.undoOp,
    onSuccess: (res) => {
      invalidateAffected(res);
      useToastStore.getState().push(res.summary);
    },
    onError: (err) => useToastStore.getState().push((err as Error).message),
  });

  const afterOperation = (res: OperationResponse) => {
    useTimelineStore.getState().clearSelection();
    invalidateAffected(res);
    useToastStore.getState().push(
      `${res.summary}했습니다`,
      res.undoable
        ? { label: "되돌리기", run: () => undoMutation.mutate(res.operation_id) }
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
          ? { label: "되돌리기", run: () => undoMutation.mutate(res.operation_id) }
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
    move: (itemIds: string[], folderId: string, copyMode: boolean) =>
      moveMutation.mutate({
        space: spaceOf(itemIds),
        item_ids: itemIds,
        dest_folder_id: folderId,
        copy_mode: copyMode,
        target_user: targetUser(),
      }),
    remove: (itemIds: string[], onSuccess?: () => void) =>
      deleteMutation.mutate(
        { space: spaceOf(itemIds), item_ids: itemIds, target_user: targetUser() },
        { onSuccess: () => onSuccess?.() },
      ),
    createFolder: (space: Space, name: string) =>
      mkdirMutation.mutate({ space, name, target_user: targetUser() }),
    undo: (opId: number) => undoMutation.mutate(opId),
    isBusy:
      moveMutation.isPending || deleteMutation.isPending || mkdirMutation.isPending,
  };
}

/** File-operation mutations with the full post-op UX (IMPROVEMENTS B-3/B-6):
 * selection auto-clears, affected timeline days invalidate precisely, and an
 * action toast offers 되돌리기 (which itself invalidates + confirms).
 * No confirmation dialogs — destructive ops are reversible via trash + undo.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type AreaScope } from "../api/client";
import type {
  ConflictStrategy,
  CreateFolderRequest,
  EmptiedFolder,
  MoveFoldersRequest,
  OperationResponse,
  RemoveFolderRequest,
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
function startProgress(label: string, unit = "장") {
  const key = genProgressKey();
  const store = useProgressStore.getState();
  store.start(key, label, unit);
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
      // 완료 프레임: 진행률이 잡혔던 작업은 100%로 스냅해 잠깐 "완료"를 보여준
      // 뒤 치운다(끝났는지 명확히). 진행률 정보가 없던 작업은 즉시 치운다.
      const st = useProgressStore.getState();
      const cur = st.current;
      if (cur && cur.key === key && cur.total > 0) {
        st.patch(key, cur.total, cur.total);
        window.setTimeout(() => useProgressStore.getState().clear(key), 900);
      } else {
        st.clear(key);
      }
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
        // folder-counts는 여기서 직접 무효화하지 않는다: 폴더 목록이 실제로
        // 바뀌면 FolderPane의 countIds(=폴더 id 목록) 키가 달라져 자연히
        // refetch된다. 매 작업마다 3회씩 강제 무효화하면(분할뷰·트리 각 pane ×
        // 청크) 폴더 수 세기 요청이 삭제 1건당 수십~백 회로 폭주해 DSM 동시성을
        // 포화시킨다(실측). 목록 변화가 없으면 카운트도 그대로라 재요청이 불필요.
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
    mutationFn: (vars: CreateFolderRequest & { _area?: AreaScope }) => {
      const { _area, ...body } = vars;
      return api.createFolder(body, _area);
    },
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
    mutationFn: (vars: MoveFoldersRequest & { _area?: AreaScope }) => {
      const { _area, ...body } = vars;
      return api.moveFolders(body, _area);
    },
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
    // 대상에 같은 이름 폴더가 있으면 409 → 전역 다이얼로그로 처리 방법 선택 후
    // 재시도. 완전 일치(원본이 대상에 다 있음)면 다이얼로그가 원본 삭제/동일
    // 안내로 분기하고, 그 외엔 합치기/이름변경/건너뛰기. (2026-07-05)
    onError: (err, variables) => {
      const info = conflictInfoOf(err);
      if (!info) return onError(err);
      useConflictStore.getState().ask({
        kind: info.kind,
        names: info.names,
        folderExtras: info.folderExtras,
        copyMode: variables.copy_mode,
        onChoose: (strategy) => {
          // 완전 일치 이동 → 선택한 원본 폴더들을 순차로 휴지통으로(대상에 이미
          // 다 있으므로 이동이 아니라 원본 정리). 여러 폴더 모두 처리한다.
          if (strategy === "purge_source") {
            void purgeSourceFolders(
              variables.space,
              variables.folder_ids,
              variables._area,
            );
            return;
          }
          const p = startProgress(
            variables.copy_mode ? "폴더 복사" : "폴더 이동",
            "%",
          );
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

  // 완전 일치한 원본 폴더들을 하나씩 순차로 휴지통으로 이동(재귀 삭제 경로 재사용
  // — 되돌리기 가능). 순차 실행이라 실 NAS의 FileStation 태스크가 겹치지 않는다.
  const purgeSourceFolders = async (
    space: Space,
    folderIds: string[],
    area?: AreaScope,
  ) => {
    for (const folderId of folderIds) {
      try {
        await rmdirMutation.mutateAsync({
          space,
          folder_id: folderId,
          recursive: true,
          target_user: targetUser(),
          _area: area,
        });
      } catch {
        // 개별 실패는 rmdirMutation.onError가 토스트로 알림 — 나머지는 계속.
      }
    }
  };

  const rmdirMutation = useMutation({
    mutationFn: (vars: RemoveFolderRequest & { _area?: AreaScope }) => {
      const { _area, ...body } = vars;
      return api.removeFolder(body, _area);
    },
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

    // 대량 이동/복사: 서버는 요청당 500장 제한이라, 500장씩 나눠 순차 전송하고
    // 진행바(장 단위)를 클라이언트가 직접 구동한다. 이름 충돌은 첫 청크에서 한 번
    // 물어보고(취소하면 중단) 선택한 방식(skip/overwrite/rename)을 남은 청크에도
    // 적용한다. 되돌리기는 청크별 개별 작업이라 요약 토스트만(작업 기록에서 개별
    // undo 가능).
    const MOVE_CHUNK = 500;
    const moveChunked = async (
      itemIds: string[],
      folderId: string,
      copyMode: boolean,
    ) => {
      if (itemIds.length === 0) return;
      const label = copyMode ? "복사" : "이동";
      const space = spaceOf(itemIds);
      const tuser = targetUser();
      const key = genProgressKey();
      useProgressStore.getState().start(key, label, "장");
      useProgressStore.getState().patch(key, 0, itemIds.length);

      let strategy: ConflictStrategy | undefined;
      let done = 0;
      let cancelled = false;
      const affected = new Map<string, { space: Space; day: string }>();
      const emptied: EmptiedFolder[] = [];

      const askStrategy = (info: NonNullable<ReturnType<typeof conflictInfoOf>>) =>
        new Promise<string | null>((resolve) => {
          useConflictStore.getState().ask({
            kind: info.kind,
            names: info.names,
            folderExtras: info.folderExtras,
            copyMode,
            onChoose: (s) => resolve(s),
            onCancel: () => resolve(null),
          });
        });

      try {
        for (let i = 0; i < itemIds.length && !cancelled; i += MOVE_CHUNK) {
          const chunk = itemIds.slice(i, i + MOVE_CHUNK);
          const base = done; // 이 청크 시작 전까지 처리된 장수
          for (;;) {
            // 청크 내부는 서버가 25장씩 처리하므로, 그 진행률을 폴링해 바를
            // 부드럽게 채운다(500장 동안 멈춘 것처럼 보이지 않게).
            const chunkKey = genProgressKey();
            const timer = window.setInterval(() => {
              api
                .opProgress(chunkKey)
                .then((r) => {
                  if (r.active)
                    useProgressStore
                      .getState()
                      .patch(
                        key,
                        Math.min(base + r.done, itemIds.length),
                        itemIds.length,
                      );
                })
                .catch(() => {});
            }, 500);
            try {
              const res = await api.opMove({
                space,
                item_ids: chunk,
                dest_folder_id: folderId,
                copy_mode: copyMode,
                conflict_strategy: strategy,
                target_user: tuser,
                progress_key: chunkKey,
              });
              done = base + chunk.length;
              useProgressStore.getState().patch(key, done, itemIds.length);
              for (const a of res.affected) affected.set(`${a.space}:${a.day}`, a);
              for (const e of res.emptied_folders ?? []) emptied.push(e);
              break;
            } catch (err) {
              const info = conflictInfoOf(err);
              if (info && strategy === undefined) {
                const chosen = await askStrategy(info);
                if (chosen === null) {
                  cancelled = true;
                  break;
                }
                strategy = chosen as ConflictStrategy;
                continue; // 같은 청크를 선택한 방식으로 재시도
              }
              throw err;
            } finally {
              window.clearInterval(timer);
            }
          }
        }
        useTimelineStore.getState().clearSelection();
        const merged = {
          affected: [...affected.values()],
          emptied_folders: emptied,
        } as unknown as OperationResponse;
        invalidateAffected(merged);
        offerCleanup(merged);
        resettleFolders();
        if (done > 0)
          useToastStore
            .getState()
            .push(`${done}장${cancelled ? " (중단됨)" : ""} ${label}했습니다`);
      } catch (err) {
        onError(err);
      } finally {
        window.setTimeout(() => useProgressStore.getState().clear(key), 1000);
      }
    };

  return {
    move: (itemIds: string[], folderId: string, copyMode: boolean) =>
      moveChunked(itemIds, folderId, copyMode),
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
    createFolder: (
      space: Space,
      name: string,
      parentId?: string,
      area?: AreaScope,
    ) =>
      mkdirMutation.mutate({
        space,
        name,
        parent_id: parentId,
        target_user: targetUser(),
        _area: area,
      }),
    moveFolders: (
      space: Space,
      folderIds: string[],
      destFolderId: string,
      copyMode: boolean,
      onSuccess?: () => void,
      area?: AreaScope,
    ) => {
      const p = startProgress(copyMode ? "폴더 복사" : "폴더 이동", "%");
      moveFoldersMutation.mutate(
        {
          space,
          folder_ids: folderIds,
          dest_folder_id: destFolderId,
          copy_mode: copyMode,
          target_user: targetUser(),
          progress_key: p.key,
          _area: area,
        },
        { onSuccess: () => onSuccess?.(), onSettled: p.stop },
      );
    },
    removeFolder: (
      space: Space,
      folderId: string,
      recursive: boolean,
      onSuccess?: () => void,
      area?: AreaScope,
    ) => {
      // 재귀 삭제는 사진 많은 폴더면 수 초 걸릴 수 있어 진행 표시를 띄운다.
      // 서버가 하위 진행을 보고하지 않으므로 총계 없는 "삭제 중…" 형태.
      const p = startProgress("삭제");
      rmdirMutation.mutate(
        {
          space,
          folder_id: folderId,
          recursive,
          target_user: targetUser(),
          _area: area,
        },
        { onSuccess: () => onSuccess?.(), onSettled: p.stop },
      );
    },
    // 선택한 여러 폴더를 휴지통으로(재귀·가역). 분할 뷰의 폴더 선택 삭제.
    // 순차 실행 — 실 NAS FileStation 태스크가 겹치지 않게(purgeSourceFolders 패턴).
    removeFolders: async (
      folders: { space: Space; id: string }[],
      area?: AreaScope,
      onDone?: () => void,
    ) => {
      // 벌크 삭제: 폴더마다 rmdirMutation.onSuccess가 folder-counts를 무효화하고
      // resettleFolders(1.5·4·8초 지연 재무효화)까지 돌면, 103개 삭제 시 폴더 수
      // 세기 재요청이 수백 회로 폭주해 DSM 동시성을 포화시킨다(실측). 그래서
      // 여기서는 조용히 순차 삭제만 하고, 캐시 무효화·재수렴·요약 토스트는
      // 배치가 끝난 뒤 한 번만 수행한다.
      // 진행률: 폴더 삭제는 클라이언트가 순차로 도는 루프라 서버 폴링 없이
      // done/total을 직접 진행바에 반영한다("12/103개 삭제 중…" → "✓ 완료").
      const store = useProgressStore.getState();
      const key = genProgressKey();
      store.start(key, "삭제", "개");
      store.patch(key, 0, folders.length);
      let done = 0;
      for (const f of folders) {
        try {
          await api.removeFolder(
            {
              space: f.space,
              folder_id: f.id,
              recursive: true,
              target_user: targetUser(),
            },
            area,
          );
          done += 1;
          useProgressStore.getState().patch(key, done, folders.length);
        } catch (err) {
          onError(err); // 실패 토스트 후 중단
          break;
        }
      }
      // 완료 프레임을 잠깐 보여준 뒤 진행바를 치운다.
      window.setTimeout(() => useProgressStore.getState().clear(key), 1200);
      if (done > 0) {
        queryClient.invalidateQueries({ queryKey: ["folders"] });
        queryClient.invalidateQueries({ queryKey: ["folder-items"] });
        queryClient.invalidateQueries({ queryKey: ["folder-counts"] });
        queryClient.invalidateQueries({ queryKey: ["buckets"] });
        queryClient.invalidateQueries({ queryKey: ["ops"] });
        resettleFolders();
        useToastStore
          .getState()
          .push(`${done}개 폴더를 휴지통으로 옮겼습니다`);
      }
      onDone?.();
    },
    undo: runUndo,
    isBusy:
      moveMutation.isPending ||
      deleteMutation.isPending ||
      mkdirMutation.isPending ||
      moveFoldersMutation.isPending ||
      rmdirMutation.isPending,
  };
}

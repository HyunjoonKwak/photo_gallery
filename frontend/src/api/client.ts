import type {
  ApiInfoResponse,
  BucketItemsResponse,
  BucketsResponse,
  CreateFolderRequest,
  DedupGroupsResponse,
  DedupJob,
  DedupJobResponse,
  DeleteRequest,
  FolderCountsResponse,
  FoldersResponse,
  ItemDetail,
  LoginRequest,
  MembersResponse,
  MoveRequest,
  OperationResponse,
  OperationsResponse,
  PersonsResponse,
  PlacesResponse,
  ProgressResponse,
  Space,
  TrashStatsResponse,
  UserInfo,
} from "./types";

import { useTimelineStore } from "../store/timeline";

/** Admin impersonation (spec 4.5): while 보는 중 다른 구성원, every photo API
 * call carries target_user so the backend reroutes the personal space to
 * that member's home. Centralized here — call sites stay unchanged. */
function ownerQS(prefix: "&" | "?" = "&"): string {
  const owner = useTimelineStore.getState().viewedOwner;
  return owner ? `${prefix}target_user=${encodeURIComponent(owner)}` : "";
}

/** Error carrying the backend's friendly message + HTTP status. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError(0, "서버에 연결할 수 없습니다.");
  }

  if (resp.status === 204) {
    return undefined as T;
  }

  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const detail =
      data && typeof data.detail === "string" ? data.detail : "요청이 실패했습니다.";
    throw new ApiError(resp.status, detail);
  }
  return data as T;
}

export const api = {
  login: (body: LoginRequest) =>
    request<UserInfo>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  me: () => request<UserInfo>("/api/auth/me"),
  systemInfo: () => request<ApiInfoResponse>("/api/system/info"),
  photoBuckets: (space: Space) =>
    request<BucketsResponse>(`/api/photos/buckets?space=${space}${ownerQS()}`),
  bucketItems: (space: Space, day: string) =>
    request<BucketItemsResponse>(
      `/api/photos/items?space=${space}&day=${day}${ownerQS()}`,
    ),
  folders: (parentId?: string) =>
    request<FoldersResponse>(
      parentId
        ? `/api/photos/folders?parent_id=${encodeURIComponent(parentId)}${ownerQS()}`
        : `/api/photos/folders${ownerQS("?")}`,
    ),
  folderItems: (folderId: string) =>
    request<BucketItemsResponse>(
      `/api/photos/folder-items?folder_id=${encodeURIComponent(folderId)}${ownerQS()}`,
    ),
  folderCounts: (ids: string[]) =>
    request<FolderCountsResponse>(
      `/api/photos/folder-counts?ids=${encodeURIComponent(ids.join(","))}${ownerQS()}`,
    ),
  searchPhotos: (space: Space, q: string) =>
    request<BucketItemsResponse>(
      `/api/photos/search?space=${space}&q=${encodeURIComponent(q)}${ownerQS()}`,
    ),
  itemDetail: (space: Space, id: string) =>
    request<ItemDetail>(
      `/api/photos/item-detail?space=${space}&id=${encodeURIComponent(id)}${ownerQS()}`,
    ),
  persons: (space: Space) =>
    request<PersonsResponse>(`/api/photos/persons?space=${space}${ownerQS()}`),
  personItems: (space: Space, id: string) =>
    request<BucketItemsResponse>(
      `/api/photos/person-items?space=${space}&id=${encodeURIComponent(id)}${ownerQS()}`,
    ),
  places: (space: Space) =>
    request<PlacesResponse>(`/api/photos/places?space=${space}${ownerQS()}`),
  placeItems: (space: Space, id: string) =>
    request<BucketItemsResponse>(
      `/api/photos/place-items?space=${space}&id=${encodeURIComponent(id)}${ownerQS()}`,
    ),
  members: () => request<MembersResponse>("/api/photos/members"),
  // ops carry target_user in the query too: the backend picks the photo
  // source (homes vs own) from the dependency, which reads query params.
  opMove: (body: MoveRequest) =>
    request<OperationResponse>(`/api/photos/ops/move${ownerQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  opDelete: (body: DeleteRequest) =>
    request<OperationResponse>(`/api/photos/ops/delete${ownerQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createFolder: (body: CreateFolderRequest) =>
    request<OperationResponse>("/api/photos/folders", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listOps: () => request<OperationsResponse>("/api/ops"),
  undoOp: (opId: number, progressKey?: string) =>
    request<OperationResponse>(
      progressKey
        ? `/api/ops/${opId}/undo?progress_key=${encodeURIComponent(progressKey)}`
        : `/api/ops/${opId}/undo`,
      { method: "POST" },
    ),
  opProgress: (key: string) =>
    request<ProgressResponse>(
      `/api/ops/progress?key=${encodeURIComponent(key)}`,
    ),
  trashStats: () => request<TrashStatsResponse>("/api/ops/trash"),
  emptyTrash: () =>
    request<OperationResponse>("/api/ops/trash/empty", { method: "POST" }),
  dedupScan: (space: Space) =>
    request<DedupJob>("/api/dedup/scan", {
      method: "POST",
      body: JSON.stringify({ space }),
    }),
  dedupStatus: (space: Space) =>
    request<DedupJobResponse>(`/api/dedup/status?space=${space}`),
  dedupCancel: (space: Space) =>
    request<DedupJobResponse>(`/api/dedup/cancel?space=${space}`, {
      method: "POST",
    }),
  dedupGroups: (space: Space, threshold: number, limit = 100) =>
    request<DedupGroupsResponse>(
      `/api/dedup/groups?space=${space}&threshold=${threshold}&limit=${limit}`,
    ),
};

/** URL for a thumbnail <img> (session cookie rides along automatically). */
/** URL for the <video> tag (Range-passthrough proxy; session cookie rides). */
export function videoUrl(space: Space, id: string): string {
  const q = new URLSearchParams({ space, id });
  const owner = useTimelineStore.getState().viewedOwner;
  if (owner) q.set("target_user", owner);
  return `/api/photos/video?${q.toString()}`;
}

export function thumbnailUrl(
  space: Space,
  id: string,
  cacheKey: string,
  size: "sm" | "xl",
): string {
  const q = new URLSearchParams({ space, id, cache_key: cacheKey, size });
  const owner = useTimelineStore.getState().viewedOwner;
  if (owner) q.set("target_user", owner);
  return `/api/photos/thumbnail?${q.toString()}`;
}

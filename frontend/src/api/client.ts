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
  MoveFoldersRequest,
  MoveCheckRequest,
  MoveCheckResponse,
  MoveRequest,
  OperationResponse,
  OperationsResponse,
  PersonsResponse,
  PlacesResponse,
  ProgressResponse,
  RemoveFolderRequest,
  Space,
  TrashStatsResponse,
  UserInfo,
  ZoneBrowseResponse,
  ZoneInfo,
  ZonesResponse,
} from "./types";

import { useTimelineStore } from "../store/timeline";

/** The active browsing scope, ridden by every photo/ops API call so the backend
 * picks the right source. Two mutually-exclusive off-normal scopes:
 * - 1차 구역(zone): FileStation folder outside Photos → ?zone=<id>
 * - 관리자 임퍼소네이션(target_user): another member's home → ?target_user=<u>
 * Centralized here so call sites stay unchanged. */
function scopeQS(prefix: "&" | "?" = "&"): string {
  const s = useTimelineStore.getState();
  if (s.activeZone) return `${prefix}zone=${encodeURIComponent(s.activeZone.id)}`;
  if (s.viewedOwner)
    return `${prefix}target_user=${encodeURIComponent(s.viewedOwner)}`;
  return "";
}

/** Error carrying the backend's friendly message + HTTP status. */
export class ApiError extends Error {
  status: number;
  /** Raw FastAPI `detail` — a string, a 422 error array, or a structured
   * object (e.g. the filename-conflict payload). Callers inspect it directly. */
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

/** Pull a human message out of a FastAPI error body. `detail` is a plain
 * string for HTTPException, an array of {msg,loc} for 422 validation errors,
 * or a structured object (with its own `message`) for richer errors. */
function errorDetail(data: unknown): string {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d.length > 0) {
      const first = d[0] as { msg?: unknown };
      if (typeof first?.msg === "string") return first.msg;
    }
    if (d && typeof d === "object" && typeof (d as { message?: unknown }).message === "string") {
      return (d as { message: string }).message;
    }
  }
  return "요청이 실패했습니다.";
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
    const raw =
      data && typeof data === "object" ? (data as { detail?: unknown }).detail : undefined;
    throw new ApiError(resp.status, errorDetail(data), raw);
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
    request<BucketsResponse>(`/api/photos/buckets?space=${space}${scopeQS()}`),
  bucketItems: (space: Space, day: string) =>
    request<BucketItemsResponse>(
      `/api/photos/items?space=${space}&day=${day}${scopeQS()}`,
    ),
  folders: (parentId?: string) =>
    request<FoldersResponse>(
      parentId
        ? `/api/photos/folders?parent_id=${encodeURIComponent(parentId)}${scopeQS()}`
        : `/api/photos/folders${scopeQS("?")}`,
    ),
  folderItems: (folderId: string, limit?: number) =>
    request<BucketItemsResponse>(
      `/api/photos/folder-items?folder_id=${encodeURIComponent(folderId)}${
        limit ? `&limit=${limit}` : ""
      }${scopeQS()}`,
    ),
  folderCounts: (ids: string[]) =>
    request<FolderCountsResponse>(
      `/api/photos/folder-counts?ids=${encodeURIComponent(ids.join(","))}${scopeQS()}`,
    ),
  searchPhotos: (space: Space, q: string) =>
    request<BucketItemsResponse>(
      `/api/photos/search?space=${space}&q=${encodeURIComponent(q)}${scopeQS()}`,
    ),
  itemDetail: (space: Space, id: string) =>
    request<ItemDetail>(
      `/api/photos/item-detail?space=${space}&id=${encodeURIComponent(id)}${scopeQS()}`,
    ),
  persons: (space: Space) =>
    request<PersonsResponse>(`/api/photos/persons?space=${space}${scopeQS()}`),
  personItems: (space: Space, id: string) =>
    request<BucketItemsResponse>(
      `/api/photos/person-items?space=${space}&id=${encodeURIComponent(id)}${scopeQS()}`,
    ),
  places: (space: Space) =>
    request<PlacesResponse>(`/api/photos/places?space=${space}${scopeQS()}`),
  placeItems: (space: Space, id: string, limit?: number) =>
    request<BucketItemsResponse>(
      `/api/photos/place-items?space=${space}&id=${encodeURIComponent(id)}${
        limit ? `&limit=${limit}` : ""
      }${scopeQS()}`,
    ),
  videos: (space: Space) =>
    request<BucketItemsResponse>(`/api/photos/videos?space=${space}${scopeQS()}`),
  members: () => request<MembersResponse>("/api/photos/members"),
  // ops carry target_user in the query too: the backend picks the photo
  // source (homes vs own) from the dependency, which reads query params.
  opMove: (body: MoveRequest) =>
    request<OperationResponse>(`/api/photos/ops/move${scopeQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  moveCheck: (body: MoveCheckRequest) =>
    request<MoveCheckResponse>(`/api/photos/ops/move-check${scopeQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  opDelete: (body: DeleteRequest) =>
    request<OperationResponse>(`/api/photos/ops/delete${scopeQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  createFolder: (body: CreateFolderRequest) =>
    request<OperationResponse>(`/api/photos/folders${scopeQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  moveFolders: (body: MoveFoldersRequest) =>
    request<OperationResponse>(`/api/photos/ops/move-folders${scopeQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  removeFolder: (body: RemoveFolderRequest) =>
    request<OperationResponse>(`/api/photos/folders/delete${scopeQS("?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listOps: () => request<OperationsResponse>("/api/ops"),
  undoOp: (opId: number, progressKey?: string) => {
    // undo도 현재 스코프(zone/owner)를 실어 보낸다 — zone 이동의 되돌리기는
    // zone 소스로 처리돼야 한다(즉시 토스트 undo는 activeZone이 맞다).
    const qs = progressKey
      ? `?progress_key=${encodeURIComponent(progressKey)}${scopeQS()}`
      : scopeQS("?");
    return request<OperationResponse>(`/api/ops/${opId}/undo${qs}`, {
      method: "POST",
    });
  },
  // 1차 구역(zone) 관리
  listZones: () => request<ZonesResponse>("/api/zones"),
  createZone: (body: { root_path: string; label: string }) =>
    request<ZoneInfo>("/api/zones", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteZone: (id: string) =>
    request<{ ok: boolean }>(`/api/zones/${id}`, { method: "DELETE" }),
  browseZonePath: (path?: string) =>
    request<ZoneBrowseResponse>(
      path
        ? `/api/zones/browse?path=${encodeURIComponent(path)}`
        : "/api/zones/browse",
    ),
  // 목적지 전용 폴더 조회: 스코프(zone/owner) 미부착 — 1차 뷰에서 2차(개인/공용
  // Photos) 폴더를 고르는 피커용. zone 스코프에 오염되지 않도록 별도 쿼리키.
  destFolders: (parentId?: string) =>
    request<FoldersResponse>(
      parentId
        ? `/api/photos/folders?parent_id=${encodeURIComponent(parentId)}`
        : "/api/photos/folders",
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
function applyScope(q: URLSearchParams): void {
  const s = useTimelineStore.getState();
  if (s.activeZone) q.set("zone", s.activeZone.id);
  else if (s.viewedOwner) q.set("target_user", s.viewedOwner);
}

export function videoUrl(space: Space, id: string): string {
  const q = new URLSearchParams({ space, id });
  applyScope(q);
  return `/api/photos/video?${q.toString()}`;
}

export function thumbnailUrl(
  space: Space,
  id: string,
  cacheKey: string,
  size: "sm" | "m" | "xl",
): string {
  const q = new URLSearchParams({ space, id, cache_key: cacheKey, size });
  applyScope(q);
  return `/api/photos/thumbnail?${q.toString()}`;
}

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
  NamePersonResponse,
  PersonsResponse,
  PlacesResponse,
  AlbumsResponse,
  AlbumMutationResponse,
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

/** 명시적 영역(분할 뷰 페인별). space는 최상위 필터·라벨용, zone/targetUser가
 * 있으면 그 스코프로 보낸다. 넘기지 않으면 전역 scopeQS로 폴백. */
export interface AreaScope {
  space: Space;
  zone?: string | null;
  targetUser?: string | null;
}
function scopeQSFor(area: AreaScope | undefined, prefix: "&" | "?" = "&"): string {
  if (!area) return scopeQS(prefix);
  if (area.zone) return `${prefix}zone=${encodeURIComponent(area.zone)}`;
  if (area.targetUser)
    return `${prefix}target_user=${encodeURIComponent(area.targetUser)}`;
  return ""; // 공용/내사진(라이브러리) — 스코프 파라미터 없음
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
  folders: (parentId?: string, area?: AreaScope) =>
    request<FoldersResponse>(
      parentId
        ? `/api/photos/folders?parent_id=${encodeURIComponent(parentId)}${scopeQSFor(area)}`
        : `/api/photos/folders${scopeQSFor(area, "?")}`,
    ),
  folderItems: (folderId: string, limit?: number, area?: AreaScope) =>
    request<BucketItemsResponse>(
      `/api/photos/folder-items?folder_id=${encodeURIComponent(folderId)}${
        limit ? `&limit=${limit}` : ""
      }${scopeQSFor(area)}`,
    ),
  // 1차 구역 폴더 id는 긴 경로라, 하위폴더가 수십~수백 개면 ids를 한 URL에 다
  // 담으면 URL이 수십 KB가 되어 프록시(NPM)/서버 한계(414)로 거부돼 카운트가
  // 안 뜬다. 작은 배치로 쪼개 병렬 요청 후 병합한다.
  folderCounts: async (
    ids: string[],
    area?: AreaScope,
  ): Promise<FolderCountsResponse> => {
    const CHUNK = 20;
    const batches: string[][] = [];
    for (let i = 0; i < ids.length; i += CHUNK)
      batches.push(ids.slice(i, i + CHUNK));
    const parts = await Promise.all(
      batches.map((b) =>
        request<FolderCountsResponse>(
          `/api/photos/folder-counts?ids=${encodeURIComponent(b.join(","))}${scopeQSFor(area)}`,
        ),
      ),
    );
    return { counts: Object.assign({}, ...parts.map((p) => p.counts)) };
  },
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
  namePerson: (personId: string, name: string) =>
    request<NamePersonResponse>(`/api/photos/persons/name`, {
      method: "POST",
      body: JSON.stringify({ person_id: personId, name }),
    }),
  mergeDuplicatePersons: () =>
    request<{ merged: number }>(`/api/photos/persons/merge-duplicates`, {
      method: "POST",
    }),
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
  // 앨범은 개인 공간 전용(scopeQS/target_user 없음).
  albums: () => request<AlbumsResponse>(`/api/photos/albums`),
  albumItems: (id: string) =>
    request<BucketItemsResponse>(
      `/api/photos/album-items?id=${encodeURIComponent(id)}`,
    ),
  createAlbum: (name: string, itemIds: string[] = []) =>
    request<AlbumMutationResponse>(`/api/photos/albums`, {
      method: "POST",
      body: JSON.stringify({ name, item_ids: itemIds }),
    }),
  addToAlbum: (albumId: string, itemIds: string[]) =>
    request<AlbumMutationResponse>(`/api/photos/albums/add`, {
      method: "POST",
      body: JSON.stringify({ album_id: albumId, item_ids: itemIds }),
    }),
  deleteAlbum: (id: string) =>
    request<AlbumMutationResponse>(
      `/api/photos/albums/${encodeURIComponent(id)}`,
      { method: "DELETE" },
    ),
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
  createFolder: (body: CreateFolderRequest, area?: AreaScope) =>
    request<OperationResponse>(`/api/photos/folders${scopeQSFor(area, "?")}`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  moveFolders: (body: MoveFoldersRequest, area?: AreaScope) =>
    request<OperationResponse>(
      `/api/photos/ops/move-folders${scopeQSFor(area, "?")}`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
  removeFolder: (body: RemoveFolderRequest, area?: AreaScope) =>
    request<OperationResponse>(
      `/api/photos/folders/delete${scopeQSFor(area, "?")}`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
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

// 썸네일 획득 로직(백엔드)이 바뀌면 올린다 — URL이 달라져 브라우저/서비스워커의
// 옛 캐시(같은 URL로 붙잡고 있던 저화질)를 무효화하고 재요청하게 한다.
const THUMB_URL_VERSION = "5";

export function thumbnailUrl(
  space: Space,
  id: string,
  cacheKey: string,
  size: "sm" | "m" | "xl",
): string {
  const q = new URLSearchParams({ space, id, cache_key: cacheKey, size });
  applyScope(q);
  q.set("tv", THUMB_URL_VERSION);
  return `/api/photos/thumbnail?${q.toString()}`;
}

import type {
  ApiInfoResponse,
  BucketItemsResponse,
  BucketsResponse,
  FoldersResponse,
  LoginRequest,
  Space,
  UserInfo,
} from "./types";

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
    request<BucketsResponse>(`/api/photos/buckets?space=${space}`),
  bucketItems: (space: Space, day: string) =>
    request<BucketItemsResponse>(`/api/photos/items?space=${space}&day=${day}`),
  folders: () => request<FoldersResponse>("/api/photos/folders"),
};

/** URL for a thumbnail <img> (session cookie rides along automatically). */
export function thumbnailUrl(
  space: Space,
  id: string,
  cacheKey: string,
  size: "sm" | "xl",
): string {
  const q = new URLSearchParams({ space, id, cache_key: cacheKey, size });
  return `/api/photos/thumbnail?${q.toString()}`;
}

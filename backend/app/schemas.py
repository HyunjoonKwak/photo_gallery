"""Pydantic request/response models (input validation per coding rules)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    account: str = Field(min_length=1, max_length=128)
    passwd: str = Field(min_length=1, max_length=256)
    otp_code: str | None = Field(default=None, max_length=16)


class UserInfo(BaseModel):
    account: str
    role: str  # admin | member
    can_browse_homes: bool  # may list /homes → gates the admin cross-user UI
    mock_mode: bool = False  # True when the backend serves fake data (dev only)


class EndpointInfo(BaseModel):
    api: str
    path: str
    min_version: int
    max_version: int
    available: bool


class ApiInfoResponse(BaseModel):
    dsm_webapi_base: str
    endpoints: list[EndpointInfo]


# --- Photos (timeline) ---


class PhotoBucket(BaseModel):
    """Count-first timeline unit: one day and how many photos it holds.

    The frontend pre-allocates section heights from counts alone, so the
    scrollbar represents the whole archive before any item detail loads.
    """

    day: str  # YYYY-MM-DD
    count: int


class PhotoItem(BaseModel):
    id: str
    filename: str
    taken_at: str  # ISO datetime
    width: int
    height: int
    size: int | None = None  # bytes
    cache_key: str
    # "photo" | "video" — videos get a ▶ badge and play in the lightbox.
    type: str = "photo"
    # Video duration in milliseconds (video_meta), None for photos.
    duration_ms: int | None = None
    # Solid placeholder color shown before the thumbnail loads (fallback when
    # no thumbhash is cached yet).
    placeholder_color: str | None = None
    # Blur placeholder (base64 thumbhash, B-2) — filled from photo_cache for
    # items the dedup scan has hashed; decoded client-side.
    thumbhash: str | None = None
    folder: str | None = None


class BucketsResponse(BaseModel):
    space: str  # personal | team
    buckets: list[PhotoBucket]  # sorted newest-day first


class BucketItemsResponse(BaseModel):
    space: str
    day: str
    items: list[PhotoItem]


class PhotoFolder(BaseModel):
    id: str
    name: str
    space: str  # personal | team
    parent_id: str | None = None  # None for top-level folders
    depth: int = 0  # nesting depth (0 = top level), for tree indentation


class FoldersResponse(BaseModel):
    folders: list[PhotoFolder]


class FolderCountsResponse(BaseModel):
    # folder id → direct item count; ids whose count failed are omitted.
    counts: dict[str, int]


class PersonInfo(BaseModel):
    """A face group from Synology Photos' built-in AI (3단계 분류)."""

    id: str
    space: str
    name: str = ""  # unnamed people come back as "" — UI shows a placeholder
    item_count: int | None = None
    # Cover face thumbnail — rides through the existing thumbnail proxy.
    cover_item_id: str | None = None
    cover_cache_key: str | None = None


class PersonsResponse(BaseModel):
    space: str
    persons: list[PersonInfo]


class PlaceInfo(BaseModel):
    """A geocoded place group from Synology Photos (GPS 기반)."""

    id: str
    space: str
    name: str
    item_count: int | None = None


class PlacesResponse(BaseModel):
    space: str
    places: list[PlaceInfo]


class ItemDetail(BaseModel):
    """On-demand detail for the lightbox info panel — folder path, EXIF and
    shooting location, fetched only when the panel opens (list responses stay
    light)."""

    id: str
    folder: str | None = None  # full folder path within the space
    # Known keys: camera, lens, aperture, exposure_time, iso, focal_length.
    # Only fields DSM actually has are included.
    exif: dict[str, str] = {}
    address: str | None = None  # geocoded shooting location


class ProgressResponse(BaseModel):
    """Bulk-operation progress snapshot (progress_key polling)."""

    active: bool
    done: int = 0
    total: int = 0
    label: str = ""


# --- File operations (move/copy/delete + undo) ---


class PlacedItem(BaseModel):
    """One item's location at a point in time — the unit of undo payloads.

    ``src_path`` / ``trash_path`` are used only by the DSM source (real
    filesystem paths for reversing FileStation operations); the mock source
    reconstructs everything from ``id`` and leaves them unset.
    """

    id: str
    space: str
    folder_id: str | None = None
    day: str  # YYYY-MM-DD (drives cache invalidation)
    src_path: str | None = None  # DSM: original absolute path
    trash_path: str | None = None  # DSM: path inside the app trash folder


class MoveRequest(BaseModel):
    space: str = "team"  # source space of the items (personal | team)
    item_ids: list[str] = Field(min_length=1, max_length=500)
    dest_folder_id: str
    copy_mode: bool = False
    # Set when an admin organizes another member's photos (audit trail).
    target_user: str | None = Field(default=None, max_length=128)
    # Client-generated key for count-based progress polling (B-6 진행 바).
    progress_key: str | None = Field(default=None, max_length=64)


class DeleteRequest(BaseModel):
    space: str = "team"
    item_ids: list[str] = Field(min_length=1, max_length=500)
    target_user: str | None = Field(default=None, max_length=128)
    progress_key: str | None = Field(default=None, max_length=64)


class CreateFolderRequest(BaseModel):
    space: str  # personal | team
    name: str = Field(min_length=1, max_length=100)
    # None → top-level; otherwise create inside this folder (분할 뷰 등).
    parent_id: str | None = Field(default=None, max_length=512)
    target_user: str | None = Field(default=None, max_length=128)


class RemoveFolderRequest(BaseModel):
    space: str = "team"
    folder_id: str = Field(min_length=1, max_length=512)
    target_user: str | None = Field(default=None, max_length=128)


class AffectedDay(BaseModel):
    space: str
    day: str


class OperationResponse(BaseModel):
    operation_id: int
    summary: str
    affected: list[AffectedDay]
    undoable: bool
    folder: PhotoFolder | None = None  # populated by create_folder


class OperationEntry(BaseModel):
    id: int
    type: str  # move | copy | delete | mkdir | empty_trash
    summary: str
    status: str  # done | undone | failed | purged (trash emptied — undo gone)
    created_at: str
    can_undo: bool
    target_user: str | None = None


class TrashStatsResponse(BaseModel):
    """App-trash contents (pending delete ops whose files sit in #trash)."""

    operations: int
    items: int


class OperationsResponse(BaseModel):
    operations: list[OperationEntry]


class MemberInfo(BaseModel):
    name: str
    # 개인 사진 공간(/homes/<u>/Photos) 존재 여부 — 없어도 선택은 가능하되
    # 드롭다운에 "(사진 없음)"으로 표기 (2026-07-03 컨셉 결정).
    has_photos: bool = True


class MembersResponse(BaseModel):
    members: list[MemberInfo]


# --- Duplicate detection (phase 2) ---


class DedupJob(BaseModel):
    id: int
    space: str
    status: str  # running | done | failed | cancelled
    processed: int
    total: int
    error: str | None = None
    updated_at: str


class DedupJobResponse(BaseModel):
    job: DedupJob | None


class DedupItem(PhotoItem):
    space: str  # items in a group may span spaces after cross-space moves


class DedupGroup(BaseModel):
    id: str
    kind: str  # exact | similar
    items: list[DedupItem]
    reference_id: str  # suggested keeper (user can override client-side)
    wasted_bytes: int


class DedupGroupsResponse(BaseModel):
    space: str
    threshold: int
    groups: list[DedupGroup]  # top-N by wasted bytes (limit param)
    total_groups: int  # total group count before the limit was applied
    total_wasted_bytes: int  # across ALL groups, not just the returned page
    scanned: bool  # False → no completed scan yet, prompt the user to scan

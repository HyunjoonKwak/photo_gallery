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
    # Solid placeholder color shown before the thumbnail loads. Replaced by a
    # thumbhash once the photo_cache pipeline lands (phase 2).
    placeholder_color: str | None = None
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


class MembersResponse(BaseModel):
    members: list[str]


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

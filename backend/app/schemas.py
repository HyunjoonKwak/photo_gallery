"""Pydantic request/response models (input validation per coding rules)."""

from __future__ import annotations

from typing import Literal

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
    # GPS 좌표(additional=["gps"]) — 장소 지도 뷰의 핀 위치. 대부분 None,
    # place_items에서만 채운다(사진에 위치정보 있을 때).
    lat: float | None = None
    lng: float | None = None


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


class NamePersonRequest(BaseModel):
    """이름 없는(또는 기존) 인물에 이름 지정. 같은 이름이 이미 있으면 자동 병합."""

    space: str = "personal"
    person_id: str
    name: str


class NamePersonResponse(BaseModel):
    person_id: str
    name: str
    merged_into: str | None = None  # 같은 이름 인물로 병합됐으면 그 id


class MergeDuplicatePersonsResponse(BaseModel):
    merged: int  # 합쳐 없앤 중복 인물 수


class PlaceInfo(BaseModel):
    """A geocoded place group from Synology Photos (GPS 기반).

    실 NAS(DSM 7.2) Geocoding list는 country/first_level/second_level 계층을
    준다 → 프론트가 국가→지역(first_level)으로 묶는다."""

    id: str
    space: str
    name: str
    item_count: int | None = None
    country: str | None = None  # e.g. "South Korea"
    country_id: int | None = None
    first_level: str | None = None  # 시/도 레벨 e.g. "Seoul", "Sydney"
    second_level: str | None = None  # 더 세부 e.g. "Gangnam-gu" (종종 빈값)


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


# How to handle items whose filename already exists in the destination folder.
# ask: default — the backend answers 409 with the conflict list so the client
# raises the 처리 방법 dialog (covers every move path, not just the dual-pane
# buttons). skip: leave conflicting items alone. overwrite: replace the existing
# file (destructive). rename: keep both via a "name_1.ext" suffix.
ConflictStrategy = Literal["ask", "skip", "overwrite", "rename"]
# Folder-level: no overwrite (replacing a whole subtree is too destructive).
# merge: fold the source folder's contents into the same-named destination
# folder (recursively); inner filename clashes are kept (the existing file
# wins, the incoming one is left behind — 사용자 결정 2026-07-05).
FolderConflictStrategy = Literal["ask", "skip", "rename", "merge"]


class MoveRequest(BaseModel):
    space: str = "team"  # source space of the items (personal | team)
    item_ids: list[str] = Field(min_length=1, max_length=500)
    dest_folder_id: str
    copy_mode: bool = False
    conflict_strategy: ConflictStrategy = "ask"
    # Set when an admin organizes another member's photos (audit trail).
    target_user: str | None = Field(default=None, max_length=128)
    # Client-generated key for count-based progress polling (B-6 진행 바).
    progress_key: str | None = Field(default=None, max_length=64)


class MoveCheckRequest(BaseModel):
    """Pre-flight: which items would collide by filename at the destination."""

    space: str = "team"
    item_ids: list[str] = Field(min_length=1, max_length=500)
    dest_folder_id: str
    target_user: str | None = Field(default=None, max_length=128)


class ConflictItem(BaseModel):
    item_id: str
    filename: str


class MoveCheckResponse(BaseModel):
    conflicts: list[ConflictItem]


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
    # False(기본): 빈 폴더만 삭제(비어있지 않으면 409). True: 사진·하위 폴더까지
    # 통째로 휴지통으로 이동(가역 — undo 시 원위치 복원). 프론트가 사용자에게
    # 확인받은 뒤에만 True로 보낸다.
    recursive: bool = False
    target_user: str | None = Field(default=None, max_length=128)


class MoveFoldersRequest(BaseModel):
    """폴더째(하위 전체 포함) 이동/복사 — 여러 폴더 한 번에."""

    space: str = "team"  # source space of the folders
    # "모두 선택"으로 한 위치의 하위 폴더 전체를 한 번에 옮길 수 있어야 한다
    # (실 NAS: 한 폴더 아래 100개 초과 흔함). CopyMove는 25개씩 청크 처리하므로
    # 상한은 병리적 요청 방지용 안전값.
    folder_ids: list[str] = Field(min_length=1, max_length=2000)
    dest_folder_id: str = Field(min_length=1, max_length=512)
    copy_mode: bool = False
    # 대상에 같은 이름의 폴더가 있을 때: ask(기본, 409로 다이얼로그) / skip /
    # rename(name_1). 폴더는 overwrite 미지원(전체 트리 소실이라 위험).
    conflict_strategy: FolderConflictStrategy = "ask"
    target_user: str | None = Field(default=None, max_length=128)
    progress_key: str | None = Field(default=None, max_length=64)


class AffectedDay(BaseModel):
    space: str
    day: str


class EmptiedFolder(BaseModel):
    """A source folder left completely empty by a move — the frontend offers a
    "빈 폴더 정리" toast to remove it (사용자 결정 2026-07-05: 자동 삭제가 아닌
    정리 제안)."""

    folder_id: str
    name: str  # basename, for the toast label
    space: str


class OperationResponse(BaseModel):
    operation_id: int
    summary: str
    affected: list[AffectedDay]
    undoable: bool
    folder: PhotoFolder | None = None  # populated by create_folder
    # Source folders emptied by this move (정리 제안 대상); empty for copy/other.
    emptied_folders: list[EmptiedFolder] = []


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


# --- 1차 구역 (기기 백업 zone) ---


class ZoneInfo(BaseModel):
    id: str
    root_path: str
    label: str


class ZonesResponse(BaseModel):
    zones: list[ZoneInfo]


class ZoneCreateRequest(BaseModel):
    root_path: str = Field(min_length=1, max_length=512)
    label: str = Field(min_length=1, max_length=100)


class ZoneBrowseEntry(BaseModel):
    name: str
    path: str


class ZoneBrowseResponse(BaseModel):
    """FileStation directory listing for the zone-registration picker (Photos
    인덱스 밖이라 일반 folders API로는 못 봄)."""

    path: str
    parent: str | None  # None at the browse root (/homes/<account>)
    dirs: list[ZoneBrowseEntry]


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

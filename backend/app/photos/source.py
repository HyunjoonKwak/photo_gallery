"""PhotoSource protocol — the single interface the photo routes talk to.

Two implementations exist:
- ``MockPhotoSource`` (mock.py): deterministic fake data, no NAS needed.
- ``DsmPhotoSource`` (dsm_source.py): real SYNO.Foto / SYNO.FotoTeam calls.

Keeping the routes source-agnostic means the frontend can be built and
exercised fully in mock mode, then flipped to DSM without UI changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..progress import ProgressFn
from ..schemas import (
    AlbumInfo,
    FolderRename,
    ItemDetail,
    MemberInfo,
    PersonInfo,
    PhotoBucket,
    PhotoFolder,
    PhotoItem,
    PlaceInfo,
    PlacedItem,
)

SPACES = ("personal", "team")
THUMB_SIZES = ("sm", "xl")

# (space, day) pairs whose cached timeline data must be refreshed client-side.
Affected = list[tuple[str, str]]


@dataclass
class MoveOutcome:
    dest_space: str
    dest_name: str = ""  # destination folder name, for the operation summary
    # Prior locations of moved items (empty in copy mode) — the undo payload.
    moved: list[PlacedItem] = field(default_factory=list)
    # Ids of copies made in copy mode — undo deletes these permanently.
    created_ids: list[str] = field(default_factory=list)
    affected: Affected = field(default_factory=list)
    # (folder_id, basename, space) of source folders emptied by this move —
    # the frontend offers to clean them up (정리 제안 토스트). Empty for copies.
    emptied: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class DeleteOutcome:
    # Locations at deletion time — the undo (restore) payload.
    deleted: list[PlacedItem] = field(default_factory=list)
    affected: Affected = field(default_factory=list)


class PhotoSource(Protocol):
    # ------------------------------------------------------------- read side
    async def buckets(self, space: str) -> list[PhotoBucket]:
        """Day buckets (newest first) with item counts only — count-first API."""
        ...

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        """All items of one day bucket, in display (taken_at) order."""
        ...

    async def folders(self, parent_id: str | None = None) -> list[PhotoFolder]:
        """One level of the folder tree (lazy).

        ``parent_id`` None → top-level folders of both spaces; otherwise → the
        direct children of that folder.
        """
        ...

    async def folder_items(
        self, folder_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        """Items currently assigned to a folder (folder view). ``limit`` caps to
        a single cheap page (미리보기 카드용 — 전체 페이징 회피)."""
        ...

    async def folder_count(self, folder_id: str) -> int:
        """Number of items directly in a folder (folder view badges)."""
        ...

    async def set_item_time(self, space: str, item_id: str, epoch: int) -> None:
        """Set a Photos item's taken time (촬영일 교정, 내 사진/공용)."""
        ...

    async def item_detail(self, space: str, item_id: str) -> ItemDetail:
        """Folder path + EXIF + location for one item (lightbox info panel)."""
        ...

    async def item_folders(
        self, space: str, item_ids: list[str]
    ) -> dict[str, str | None]:
        """id → folder path for a batch of items (dedup group cards)."""
        ...

    async def search_items(self, space: str, keyword: str) -> list[PhotoItem]:
        """Keyword search (filename/folder/tag — DSM's own index)."""
        ...

    # ------------------------------------------- AI classification (3단계)
    # Synology Photos' own AI has already indexed faces (인물) and GPS places
    # (장소); we read those groups and reuse the move+undo pipeline to act on
    # them — no external AI API, no extra NAS load (docs/IMPROVEMENTS.md 결정).

    async def persons(self, space: str) -> list[PersonInfo]:
        """Face groups of one space, biggest first."""
        ...

    async def person_items(self, space: str, person_id: str) -> list[PhotoItem]:
        """All items containing a person."""
        ...

    async def name_person(self, space: str, person_id: str, name: str) -> dict:
        """인물에 이름 지정. 같은 이름의 인물이 이미 있으면 자동 병합.
        반환 dict: {"name", "merged_into": 병합 대상 id 또는 None}."""
        ...

    async def merge_duplicate_persons(self, space: str) -> dict:
        """같은 이름의 인물이 여럿이면 하나(가장 큰 그룹)로 합친다.
        반환 dict: {"merged": 합쳐 없앤 인물 수}."""
        ...

    async def places(self, space: str) -> list[PlaceInfo]:
        """Geocoded place groups of one space."""
        ...

    async def place_items(
        self, space: str, place_id: str, limit: int | None = None
    ) -> list[PhotoItem]:
        """All items taken at a place. ``limit`` caps to a single cheap page."""
        ...

    async def videos(self, space: str) -> list[PhotoItem]:
        """All videos in a space (앨범 · 비디오), newest first — the library-wide
        video collection the timeline/folder filters can't produce cheaply."""
        ...

    # ---- User albums (SYNO.Foto.Browse.NormalAlbum) — 개인 공간 전용 ----
    # 앨범은 로그인 사용자 본인의 개인 앨범이며 공유(FotoTeam) 앨범 API는 없다
    # (2026-07-07 실 NAS 프로브). space 인자는 인터페이스 일관성용이며 구현은
    # personal만 의미가 있다(team은 빈 목록/미지원).

    async def albums(self, space: str) -> list[AlbumInfo]:
        """User-curated albums, newest first."""
        ...

    async def album_items(self, space: str, album_id: str) -> list[PhotoItem]:
        """All items in an album."""
        ...

    async def create_album(
        self, space: str, name: str, item_ids: list[str]
    ) -> AlbumInfo:
        """Create a normal album (optionally seeded with items). Returns it."""
        ...

    async def add_to_album(
        self, space: str, album_id: str, item_ids: list[str]
    ) -> int:
        """Add items to an album. Returns how many were added."""
        ...

    async def delete_album(self, space: str, album_id: str) -> None:
        """Delete an album (the photos themselves are untouched)."""
        ...

    # ---- 폴더 이름 정리 (날짜부 밑줄→하이픈) ----

    async def audit_folder_names(self, root_id: str | None) -> list[FolderRename]:
        """root_id(경로형/None=영역 루트) 하위를 재귀로 훑어 이름 규칙에 어긋난
        폴더와 교정안을 반환. 1차 구역/homes 전용(마운트 스캔)."""
        ...

    async def rename_folder(
        self, space: str, folder_id: str, new_name: str
    ) -> tuple[str, str]:
        """폴더 이름 변경(제자리). (새 id, 새 이름) 반환."""
        ...

    async def members(self) -> list[MemberInfo]:
        """Family member accounts + 개인 사진 공간 유무 (admin: cross-user)."""
        ...

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        """Thumbnail bytes + content type. ``size`` is ``sm`` (grid) or ``xl``."""
        ...

    async def video_stream(
        self, space: str, item_id: str, range_header: str | None
    ):
        """Streaming response for video playback (Range passthrough).

        Returns an httpx.Response opened in streaming mode; the API layer
        forwards status/headers/chunks to the browser ``<video>`` tag.
        """
        ...

    async def item_hashes(self, space: str, item: PhotoItem) -> tuple[str, str, str]:
        """(sha256, phash-hex, thumbhash-base64) — dedup (D절) + blur
        placeholder (B-2).

        DSM computes over the small thumbnail (원본 전송 회피); mock simulates
        deterministic sha/phash with planted duplicate clusters and encodes a
        real thumbhash from a synthetic gradient.
        """
        ...

    # ----------------------------------------------------------- write side
    async def conflicts(
        self, space: str, item_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str]]:
        """(item_id, filename) pairs whose filename already exists in the dest
        folder — the pre-flight check that drives the 충돌 처리 dialog."""
        ...

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
        conflict_strategy: str = "skip",
    ) -> MoveOutcome:
        """Move (or copy) items into a folder — cross-space allowed.

        ``space`` is the source space of the items (needed by the DSM source to
        resolve the share prefix; the mock source ignores it). ``on_progress``
        receives (done, total) as chunks complete (B-6 진행 바).
        ``conflict_strategy`` decides same-filename handling: skip | overwrite |
        rename (see schemas.ConflictStrategy).
        """
        ...

    async def delete(
        self,
        space: str,
        item_ids: list[str],
        on_progress: ProgressFn | None = None,
    ) -> DeleteOutcome:
        """Send items to the app trash (never permanent — spec: 휴지통 + Undo)."""
        ...

    # ------------------------------------------------------ undo primitives
    async def place(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        """Put items back at recorded locations (undo of a move)."""
        ...

    async def restore(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        """Bring items back from trash (undo of a delete)."""
        ...

    async def remove_items(self, item_ids: list[str]) -> Affected:
        """Remove copies made by a copy operation (undo of a copy)."""
        ...

    async def create_folder(
        self, space: str, name: str, parent_id: str | None = None
    ) -> PhotoFolder:
        """Create a folder — top-level when parent_id is None, else nested."""
        ...

    async def purge_trash(self) -> None:
        """Permanently remove all app-trash contents (휴지통 비우기).

        The ONLY irreversible operation in the app — callers must confirm
        (IMPROVEMENTS B-6: 영구 삭제만 확인 다이얼로그).
        """
        ...

    async def remove_folder(self, folder_id: str) -> bool:
        """Remove an empty folder (undo of mkdir). False if not empty/removable."""
        ...

    async def trash_folder(self, space: str, folder_id: str) -> dict:
        """Recursively send a whole folder (photos + subfolders) to the trash —
        the reversible alternative to a permanent recursive delete. Returns
        ``{"name": 표시명, "undo": <source-specific payload>}``; the undo payload
        feeds ``restore_folder`` to bring the folder back to its original place.
        """
        ...

    async def restore_folder(self, undo_payload: dict) -> None:
        """Undo of trash_folder: move the folder back to its original location."""
        ...

    # -------------------------------------------------- folder-level move
    async def folder_conflicts(
        self, space: str, folder_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str, int]]:
        """(folder_id, name, extra_count) of source folders whose name already
        exists as a subfolder of the destination — drives the folder 충돌 처리
        dialog. ``extra_count`` is how many items the source holds that the
        destination twin does NOT (by name+size, recursively): 0 means the
        source is fully contained in the destination (완전 일치 — 이동 시 원본
        삭제 제안, 복사 시 "이미 동일" 안내)."""
        ...

    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
        conflict_strategy: str = "skip",
    ) -> dict:
        """Move/copy whole folders (subtree 포함) into a destination folder.

        ``conflict_strategy`` handles a same-named folder at the destination:
        skip | rename (name_1) | merge (fold contents into the existing folder,
        recursively; inner file clashes keep the existing file). A merge in move
        mode deletes the source folder once emptied (병합 완료), reversible via
        undo. Returns ``{"names": [표시명...], "undo": <source-specific payload>}``
        — the undo payload feeds ``revert_move_folders``.
        """
        ...

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        """Undo of move_folders: move back (move) / delete copies (copy)."""
        ...

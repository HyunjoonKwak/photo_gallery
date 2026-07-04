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

    async def folder_items(self, folder_id: str) -> list[PhotoItem]:
        """Items currently assigned to a folder (folder view)."""
        ...

    async def folder_count(self, folder_id: str) -> int:
        """Number of items directly in a folder (folder view badges)."""
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

    async def places(self, space: str) -> list[PlaceInfo]:
        """Geocoded place groups of one space."""
        ...

    async def place_items(self, space: str, place_id: str) -> list[PhotoItem]:
        """All items taken at a place."""
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
    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
    ) -> MoveOutcome:
        """Move (or copy) items into a folder — cross-space allowed.

        ``space`` is the source space of the items (needed by the DSM source to
        resolve the share prefix; the mock source ignores it). ``on_progress``
        receives (done, total) as chunks complete (B-6 진행 바).
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

    # -------------------------------------------------- folder-level move
    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
    ) -> dict:
        """Move/copy whole folders (subtree 포함) into a destination folder.

        Returns ``{"names": [표시명...], "undo": <source-specific payload>}`` —
        the undo payload feeds ``revert_move_folders``.
        """
        ...

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        """Undo of move_folders: move back (move) / delete copies (copy)."""
        ...

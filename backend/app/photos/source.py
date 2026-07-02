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
from ..schemas import PhotoBucket, PhotoFolder, PhotoItem, PlacedItem

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

    async def members(self) -> list[str]:
        """Family member accounts (admin: cross-user organizing)."""
        ...

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        """Thumbnail bytes + content type. ``size`` is ``sm`` (grid) or ``xl``."""
        ...

    async def item_hashes(self, space: str, item: PhotoItem) -> tuple[str, str]:
        """(sha256, phash-hex) for duplicate detection (D절).

        DSM computes over the small thumbnail (원본 전송 회피); mock simulates
        deterministic hashes with planted duplicate clusters.
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

    async def create_folder(self, space: str, name: str) -> PhotoFolder:
        ...

    async def remove_folder(self, folder_id: str) -> bool:
        """Remove an empty folder (undo of mkdir). False if not empty/removable."""
        ...

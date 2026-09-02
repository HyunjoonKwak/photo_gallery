"""Central Gallery write policy for the Gallery → Desk transition.

The frontend capabilities are only presentation hints. Every write boundary
must still use the FastAPI dependencies in ``api.deps`` so a hidden button or
direct HTTP call cannot bypass the selected mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import GalleryWriteMode, Settings


@dataclass(frozen=True)
class GalleryCapabilities:
    physical_mutations: bool
    undo_drain: bool
    synology_curation: bool
    legacy_date_repair: bool


def capabilities_for(settings: Settings, role: str) -> GalleryCapabilities:
    """Return the effective capabilities for one authenticated session."""
    mode: GalleryWriteMode = settings.gallery_write_mode
    return GalleryCapabilities(
        physical_mutations=mode == "legacy",
        undo_drain=mode in ("legacy", "drain"),
        # Normal albums and person naming/merge only mutate Synology's logical
        # index. DSM remains the per-account authorization boundary.
        synology_curation=True,
        legacy_date_repair=(
            role == "admin"
            and settings.gallery_legacy_date_repair
            and mode in ("legacy", "drain")
        ),
    )

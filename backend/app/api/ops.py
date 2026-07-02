"""Operation history endpoints: list recent operations + undo (spec 9.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import Settings, get_settings
from ..operations import list_operations, undo_operation
from ..photos.source import PhotoSource
from ..schemas import OperationResponse, OperationsResponse, ProgressResponse
from ..session_store import Session
from .deps import get_current_session, get_photo_source
from .. import progress as progress_registry

router = APIRouter(prefix="/api/ops", tags=["operations"])


@router.get("", response_model=OperationsResponse)
async def operations(
    limit: int = Query(30, ge=1, le=100),
    _session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> OperationsResponse:
    return OperationsResponse(operations=list_operations(settings.sqlite_path, limit))


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(
    key: str = Query(min_length=1, max_length=64),
    _session: Session = Depends(get_current_session),
) -> ProgressResponse:
    """Bulk-operation progress for a progress_key (B-6 개수 기반 진행 바)."""
    entry = progress_registry.get(key)
    if entry is None:
        return ProgressResponse(active=False)
    return ProgressResponse(
        active=True, done=entry.done, total=entry.total, label=entry.label
    )


@router.post("/{op_id}/undo", response_model=OperationResponse)
async def undo(
    op_id: int,
    progress_key: str | None = Query(default=None, max_length=64),
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    try:
        return await undo_operation(
            source,
            settings.sqlite_path,
            op_id,
            on_progress=progress_registry.callback(progress_key, "되돌리기"),
        )
    finally:
        progress_registry.clear(progress_key)

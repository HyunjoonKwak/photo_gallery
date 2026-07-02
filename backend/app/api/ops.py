"""Operation history endpoints: list recent operations + undo (spec 9.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import Settings, get_settings
from ..operations import list_operations, undo_operation
from ..photos.source import PhotoSource
from ..schemas import OperationResponse, OperationsResponse
from ..session_store import Session
from .deps import get_current_session, get_photo_source

router = APIRouter(prefix="/api/ops", tags=["operations"])


@router.get("", response_model=OperationsResponse)
async def operations(
    limit: int = Query(30, ge=1, le=100),
    _session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> OperationsResponse:
    return OperationsResponse(operations=list_operations(settings.sqlite_path, limit))


@router.post("/{op_id}/undo", response_model=OperationResponse)
async def undo(
    op_id: int,
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    return await undo_operation(source, settings.sqlite_path, op_id)

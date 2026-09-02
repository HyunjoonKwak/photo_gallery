"""Operation history endpoints: list recent operations + undo (spec 9.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import Settings, get_settings
from ..operations import (
    execute_empty_trash,
    execute_restore_items,
    list_operations,
    list_trash_items,
    trash_stats,
    undo_operation,
)
from ..photos.source import PhotoSource
from ..schemas import (
    OperationResponse,
    OperationsResponse,
    ProgressResponse,
    TrashItemsResponse,
    TrashRestoreRequest,
    TrashStatsResponse,
)
from ..session_store import Session
from .deps import (
    get_current_session,
    get_photo_source,
    require_physical_mutations,
    require_recovery,
)
from .. import progress as progress_registry

router = APIRouter(prefix="/api/ops", tags=["operations"])


def _viewer(session: Session) -> str | None:
    """계정별 열람 필터 — 일반 사용자는 본인 작업만, 관리자는 전체(None).
    다른 가족의 개인 공간 파일명이 작업 기록/휴지통으로 새는 것을 막는다."""
    return None if session.role == "admin" else session.account


@router.get("", response_model=OperationsResponse)
async def operations(
    limit: int = Query(30, ge=1, le=100),
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> OperationsResponse:
    return OperationsResponse(
        operations=list_operations(settings.sqlite_path, limit, _viewer(session))
    )


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


@router.get("/trash", response_model=TrashStatsResponse)
async def get_trash_stats(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> TrashStatsResponse:
    ops_count, items = trash_stats(settings.sqlite_path, _viewer(session))
    return TrashStatsResponse(operations=ops_count, items=items)


@router.get("/trash-items", response_model=TrashItemsResponse)
async def get_trash_items(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> TrashItemsResponse:
    """휴지통 내용(사진 단위) — 개별 복원용. 작업로그의 placements를 펼친다."""
    return TrashItemsResponse(
        items=list_trash_items(  # type: ignore[arg-type]
            settings.sqlite_path, viewer=_viewer(session)
        )
    )


@router.post(
    "/trash-restore",
    response_model=OperationResponse,
    dependencies=[Depends(require_recovery)],
)
async def restore_trash_items(
    req: TrashRestoreRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    """선택한 사진만 원위치로 복원(작업 undo의 부분집합)."""
    try:
        return await execute_restore_items(
            source,
            settings.sqlite_path,
            user=session.account,
            entries=[(e.op_id, e.item_id) for e in req.entries],
            viewer=_viewer(session),
            on_progress=(
                progress_registry.callback(req.progress_key, "복원")
                if req.progress_key
                else None
            ),
        )
    finally:
        if req.progress_key:
            progress_registry.clear(req.progress_key)


@router.post(
    "/trash/empty",
    response_model=OperationResponse,
    dependencies=[Depends(require_physical_mutations)],
)
async def empty_trash(
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    """휴지통 비우기 — 유일한 비가역 작업. 삭제된 undo들도 함께 무효화되므로
    가족 전체에 영향: 관리자 전용."""
    if session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자만 휴지통을 비울 수 있습니다.",
        )
    return await execute_empty_trash(
        source, settings.sqlite_path, user=session.account
    )


@router.post(
    "/{op_id}/undo",
    response_model=OperationResponse,
    dependencies=[Depends(require_recovery)],
)
async def undo(
    op_id: int,
    progress_key: str | None = Query(default=None, max_length=64),
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    try:
        return await undo_operation(
            source,
            settings.sqlite_path,
            op_id,
            viewer=_viewer(session),
            on_progress=progress_registry.callback(progress_key, "되돌리기"),
        )
    finally:
        progress_registry.clear(progress_key)

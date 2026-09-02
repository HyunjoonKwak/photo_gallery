"""Duplicate-detection endpoints: scan job control + duplicate groups.

The groups response *is* the dry-run (D절): the UI shows exactly what would
be deleted and how much space it saves; actual deletion reuses the standard
/api/photos/ops/delete flow (trash + operation log + undo).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..config import Settings, get_settings
from ..dedup import build_groups, cancel_scan, latest_job, start_scan
from ..photos.source import PhotoSource
from ..schemas import DedupGroupsResponse, DedupJob, DedupJobResponse
from ..session_store import Session
from .deps import get_current_session, get_photo_source, require_physical_mutations

router = APIRouter(prefix="/api/dedup", tags=["dedup"])

Space = Literal["personal", "team"]


class ScanRequest(BaseModel):
    space: Space
    # 테스트/소규모 데이터용: 응답 전에 스캔을 끝냄. UI는 비동기(폴링) 사용.
    sync: bool = Field(default=False)


@router.post(
    "/scan",
    response_model=DedupJob,
    dependencies=[Depends(require_physical_mutations)],
)
async def scan(
    req: ScanRequest,
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> DedupJob:
    return await start_scan(source, settings.sqlite_path, req.space, sync=req.sync)


@router.get("/status", response_model=DedupJobResponse)
async def status(
    space: Space = Query("team"),
    _session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> DedupJobResponse:
    return DedupJobResponse(job=latest_job(settings.sqlite_path, space))


@router.post(
    "/cancel",
    response_model=DedupJobResponse,
    dependencies=[Depends(require_physical_mutations)],
)
async def cancel(
    space: Space = Query("team"),
    _session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> DedupJobResponse:
    cancel_scan(settings.sqlite_path, space)
    return DedupJobResponse(job=latest_job(settings.sqlite_path, space))


@router.get("/groups", response_model=DedupGroupsResponse)
async def groups(
    space: Space = Query("team"),
    # 8밴드×8비트 후보 버킷팅은 hamming ≤ 7까지 재현율을 보장하므로 상한 7.
    threshold: int = Query(5, ge=0, le=7),
    # 이미 wasted 내림차순 정렬 → 상위 N개만 반환(카드 수천 장 렌더 방지).
    limit: int = Query(100, ge=1, le=500),
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> DedupGroupsResponse:
    job = latest_job(settings.sqlite_path, space)
    scanned = job is not None and job.status == "done"
    result = build_groups(settings.sqlite_path, space, threshold) if scanned else []
    top = result[:limit]

    # Folder locations for the visible groups (photo_cache stores filenames
    # only) — one batched DSM call per ~100 items; a lookup failure just
    # leaves those folders blank rather than failing the response.
    ids = [it.id for g in top for it in g.items]
    if ids:
        try:
            folders = await source.item_folders(space, ids)
        except Exception:  # noqa: BLE001 - cards remain useful without folders
            folders = {}
        if folders:
            top = [
                g.model_copy(
                    update={
                        "items": [
                            it.model_copy(update={"folder": folders.get(it.id)})
                            for it in g.items
                        ]
                    }
                )
                for g in top
            ]

    return DedupGroupsResponse(
        space=space,
        threshold=threshold,
        groups=top,
        total_groups=len(result),
        total_wasted_bytes=sum(g.wasted_bytes for g in result),
        scanned=scanned,
    )

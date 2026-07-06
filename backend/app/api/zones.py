"""1차 구역(기기 백업 zone) 등록/조회/삭제 + 등록용 폴더 탐색.

Zone = Synology Photos 인덱스 밖의 폴더라 일반 folders API(Foto 인덱스)로는
못 본다. 등록 UI는 여기 ``/browse``(FileStation 디렉터리 탐색)로 폴더를 고른다.
모든 라우트는 로그인 계정(session.account) 스코프 — 남의 zone은 못 본다.
"""

from __future__ import annotations

import posixpath

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..schemas import (
    ZoneBrowseEntry,
    ZoneBrowseResponse,
    ZoneCreateRequest,
    ZoneInfo,
    ZonesResponse,
)
from ..session_store import Session
from ..zone_store import (
    ZonePathError,
    create_zone,
    delete_zone,
    list_zones,
    validate_zone_root,
)
from .deps import get_current_session, get_dsm_client

router = APIRouter(prefix="/api/zones", tags=["zones"])


@router.get("", response_model=ZonesResponse)
async def get_zones(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> ZonesResponse:
    zones = list_zones(settings.sqlite_path, session.account)
    return ZonesResponse(
        zones=[ZoneInfo(id=z.id, root_path=z.root_path, label=z.label) for z in zones]
    )


@router.get("/browse", response_model=ZoneBrowseResponse)
async def browse_folders(
    path: str | None = Query(default=None, max_length=512),
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
) -> ZoneBrowseResponse:
    """등록 UI용 폴더 탐색 — 내 홈(/homes/<account>) 아래를 파고든다."""
    account = session.account
    base = f"/homes/{account}"
    target = path or base
    try:
        target = validate_zone_root(account, target)
    except ZonePathError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    if settings.mock_mode:
        from ..photos.mock import mock_zone_subdirs

        dirs = [ZoneBrowseEntry(name=n, path=p) for n, p in mock_zone_subdirs(target)]
    else:
        try:
            data = await dsm.call(
                "SYNO.FileStation.List",
                "list",
                version=2,
                sid=session.sid,
                extra={
                    "folder_path": target,
                    "limit": 2000,
                    "filetype": "dir",
                    "sort_by": "name",
                },
            )
        except DsmError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "폴더를 열 수 없습니다."
            ) from exc
        dirs = [
            ZoneBrowseEntry(name=f.get("name", ""), path=f.get("path", ""))
            for f in data.get("files", [])
            if f.get("name") != "@eaDir"
        ]

    parent = None if target == base else posixpath.dirname(target)
    return ZoneBrowseResponse(path=target, parent=parent, dirs=dirs)


@router.post("", response_model=ZoneInfo)
async def add_zone(
    req: ZoneCreateRequest,
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
) -> ZoneInfo:
    try:
        root = validate_zone_root(session.account, req.root_path)
    except ZonePathError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    # 실 NAS에서는 존재 확인(best-effort). mock은 결정적 트리라 생략.
    if not settings.mock_mode:
        try:
            await dsm.call(
                "SYNO.FileStation.List",
                "list",
                version=2,
                sid=session.sid,
                extra={"folder_path": root, "limit": 1},
            )
        except DsmError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "폴더를 찾을 수 없습니다. 경로를 확인하세요.",
            ) from exc
    zone = create_zone(settings.sqlite_path, session.account, root, req.label.strip())
    return ZoneInfo(id=zone.id, root_path=zone.root_path, label=zone.label)


@router.delete("/{zone_id}")
async def remove_zone(
    zone_id: str,
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not delete_zone(settings.sqlite_path, session.account, zone_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "구역을 찾을 수 없습니다.")
    return {"ok": True}

"""1차 구역(기기 백업 zone) 등록/조회/삭제 + 등록용 폴더 탐색.

Zone = Synology Photos 인덱스 밖의 폴더라 일반 folders API(Foto 인덱스)로는
못 본다. 등록 UI는 여기 ``/browse``(FileStation 디렉터리 탐색)로 폴더를 고른다.
모든 라우트는 로그인 계정(session.account) 스코프 — 남의 zone은 못 본다.
"""

from __future__ import annotations

import os
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
    mark_zone_seen,
    validate_zone_root,
)
from .deps import get_current_session, get_dsm_client, require_physical_mutations

router = APIRouter(prefix="/api/zones", tags=["zones"])

# 신규 유입 카운트 캐시: zone_id -> (monotonic_ts, count). 디스크 스캔(os.walk)
# 을 zones 목록 호출마다 반복하지 않게 짧게 캐시.
_NEW_COUNT_CACHE: dict[str, tuple[float, int]] = {}
_NEW_COUNT_TTL = 60.0


def _count_new_files(disk_root: str, since_epoch: float) -> int:
    """since 이후 NAS에 '생성'된 파일 수. 기준은 ctime — 백업 앱이 mtime을
    촬영시각으로 넣으므로(2026-07-12) mtime은 신규 판별에 못 쓴다. 새 파일의
    ctime은 업로드 시각이라 정확하다."""
    count = 0
    for root, dirs, files in os.walk(disk_root):
        dirs[:] = [d for d in dirs if not d.startswith(("@", "#", "."))]
        for f in files:
            if f.startswith("."):
                continue
            try:
                if os.stat(os.path.join(root, f)).st_ctime > since_epoch:
                    count += 1
            except OSError:
                continue
    return count


async def _zone_new_count(zone) -> int:
    import asyncio as _asyncio
    import time as _time
    from datetime import datetime, timezone

    from ..photos.capture_fix import disk_path

    cached = _NEW_COUNT_CACHE.get(zone.id)
    if cached and (_time.monotonic() - cached[0]) < _NEW_COUNT_TTL:
        return cached[1]
    droot = disk_path(zone.root_path)
    if not droot or not os.path.isdir(droot) or not zone.last_seen_at:
        return 0
    try:
        seen = (
            datetime.fromisoformat(zone.last_seen_at)
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
    except ValueError:
        return 0
    n = await _asyncio.to_thread(_count_new_files, droot, seen)
    _NEW_COUNT_CACHE[zone.id] = (_time.monotonic(), n)
    return n


@router.get("", response_model=ZonesResponse)
async def get_zones(
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> ZonesResponse:
    zones = list_zones(settings.sqlite_path, session.account)
    out = []
    for z in zones:
        out.append(
            ZoneInfo(
                id=z.id,
                root_path=z.root_path,
                label=z.label,
                new_count=await _zone_new_count(z),
            )
        )
    return ZonesResponse(zones=out)


@router.post("/{zone_id}/seen")
async def zone_seen(
    zone_id: str,
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """구역을 열람했음 표시 — 신규 유입 뱃지 기준 시각 리셋."""
    mark_zone_seen(settings.sqlite_path, session.account, zone_id)
    _NEW_COUNT_CACHE.pop(zone_id, None)
    return {"ok": True}


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


@router.post(
    "",
    response_model=ZoneInfo,
    dependencies=[Depends(require_physical_mutations)],
)
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


@router.delete("/{zone_id}", dependencies=[Depends(require_physical_mutations)])
async def remove_zone(
    zone_id: str,
    session: Session = Depends(get_current_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not delete_zone(settings.sqlite_path, session.account, zone_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "구역을 찾을 수 없습니다.")
    return {"ok": True}

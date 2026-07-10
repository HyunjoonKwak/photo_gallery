"""Photo timeline endpoints (count-first buckets → per-day items → thumbnails).

The shape follows the Google Photos / Immich timeline pattern documented in
docs/IMPROVEMENTS.md B-1: the client first fetches day buckets with counts
only (cheap, whole archive), pre-allocates section heights, then lazily loads
each day's items as the viewport approaches them. Day-level buckets keep any
single geometry computation small (the Immich #28861 freeze mitigation).
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ..config import Settings, get_settings
from ..dedup import fill_thumbhashes
from ..dsm.errors import SESSION_INVALID_CODES, DsmError
from ..operations import (
    execute_create_folder,
    execute_delete,
    execute_move,
    execute_move_folders,
    execute_remove_folder,
)
from ..photos.source import PhotoSource
from ..photos.thumb_cache import THUMB_MEDIA_TYPE, ThumbCache
from .. import progress
from ..photos import capture_fix
from ..photos.capture_date import parse_from_filename
from ..photos.dsm_source import invalidate_bucket_cache
from ..schemas import (
    AddToAlbumRequest,
    AlbumMutationResponse,
    AlbumsResponse,
    BucketItemsResponse,
    BucketsResponse,
    CaptureAuditItem,
    CaptureAuditResponse,
    CaptureFixFotoRequest,
    CaptureFixManualRequest,
    CaptureFixRequest,
    CaptureFixResponse,
    CreateAlbumRequest,
    CreateFolderRequest,
    FolderAuditResponse,
    RenameFolderRequest,
    RenameFolderResponse,
    DeleteRequest,
    FolderCountsResponse,
    FoldersResponse,
    ConflictItem,
    ItemDetail,
    MembersResponse,
    MoveCheckRequest,
    MoveCheckResponse,
    MoveFoldersRequest,
    MoveRequest,
    OperationResponse,
    MergeDuplicatePersonsResponse,
    NamePersonRequest,
    NamePersonResponse,
    PersonsResponse,
    PlacesResponse,
    RemoveFolderRequest,
)
from ..session_store import Session
from .deps import get_current_session, get_photo_source

router = APIRouter(prefix="/api/photos", tags=["photos"])

Space = Literal["personal", "team"]
# sm=grid, m=sm이 broken일 때 폴백(동영상 등), xl=라이트박스. 전부 DSM 실제
# 썸네일 사이즈명과 1:1 (SYNO.Foto.Thumbnail size 파라미터).
ThumbSize = Literal["sm", "m", "xl"]


def _check_target_user(session: Session, target_user: str | None) -> None:
    """Only admins may act on another member's behalf (audit-logged)."""
    if target_user and target_user != session.account and session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자만 다른 구성원을 대상으로 작업할 수 있습니다.",
        )


@router.get("/buckets", response_model=BucketsResponse)
async def list_buckets(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> BucketsResponse:
    buckets = await source.buckets(space)
    return BucketsResponse(space=space, buckets=buckets)


@router.get("/items", response_model=BucketItemsResponse)
async def list_bucket_items(
    day: str,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    try:
        date.fromisoformat(day)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="day 형식은 YYYY-MM-DD 입니다.",
        ) from exc
    items = fill_thumbhashes(settings.sqlite_path, await source.items(space, day))
    return BucketItemsResponse(space=space, day=day, items=items)


@router.get("/folders", response_model=FoldersResponse)
async def list_folders(
    parent_id: str | None = None,
    source: PhotoSource = Depends(get_photo_source),
) -> FoldersResponse:
    """One level of the folder tree. Omit parent_id for top-level folders."""
    return FoldersResponse(folders=await source.folders(parent_id))


@router.get("/folder-items", response_model=BucketItemsResponse)
async def list_folder_items(
    folder_id: str,
    limit: int | None = Query(None, ge=1, le=100),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """Items assigned to one folder (folder view). Space rides on the folder.
    ``limit`` (미리보기 카드) caps to a cheap single page."""
    items = fill_thumbhashes(
        settings.sqlite_path, await source.folder_items(folder_id, limit)
    )
    folders = {f.id: f for f in await source.folders()}
    space = folders[folder_id].space if folder_id in folders else "team"
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/folder-counts", response_model=FolderCountsResponse)
async def get_folder_counts(
    ids: str,
    source: PhotoSource = Depends(get_photo_source),
) -> FolderCountsResponse:
    """Direct item counts for a set of folders (folder view badges).

    Comma-separated ids, counted in parallel; a folder whose count fails is
    omitted (the UI simply hides that badge) so one bad id can't 500 the batch.
    """
    id_list = [i.strip() for i in ids.split(",") if i.strip()][:200]

    async def one(fid: str) -> tuple[str, int | None]:
        try:
            return fid, await source.folder_count(fid)
        except Exception:
            return fid, None

    pairs = await asyncio.gather(*(one(fid) for fid in id_list))
    return FolderCountsResponse(
        counts={fid: n for fid, n in pairs if n is not None}
    )


@router.get("/members", response_model=MembersResponse)
async def list_members(
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> MembersResponse:
    if session.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="관리자만 가족 구성원 목록을 볼 수 있습니다.",
        )
    return MembersResponse(members=await source.members())


@router.get("/search", response_model=BucketItemsResponse)
async def search_photos(
    q: str = Query(min_length=1, max_length=100),
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """Keyword search over DSM's own index (filename/folder/tag)."""
    items = fill_thumbhashes(
        settings.sqlite_path, await source.search_items(space, q)
    )
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/item-detail", response_model=ItemDetail)
async def get_item_detail(
    id: str,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> ItemDetail:
    """Lightbox info panel: folder path + EXIF + location, fetched on open."""
    return await source.item_detail(space, id)


# --------------------------------------------- AI classification (3단계)
# Synology Photos' built-in AI groups (faces, GPS places) — read-only here;
# acting on them reuses the regular move/delete + undo pipeline.


@router.get("/persons", response_model=PersonsResponse)
async def list_persons(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> PersonsResponse:
    return PersonsResponse(space=space, persons=await source.persons(space))


@router.post("/persons/name", response_model=NamePersonResponse)
async def name_person(
    req: NamePersonRequest,
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> NamePersonResponse:
    """인물에 이름 지정(같은 이름 있으면 자동 병합). 얼굴 인식은 개인 공간
    전용이라 space는 personal 고정 취급."""
    result = await source.name_person("personal", req.person_id, req.name)
    return NamePersonResponse(
        person_id=req.person_id,
        name=result["name"],
        merged_into=result.get("merged_into"),
    )


@router.post("/persons/merge-duplicates", response_model=MergeDuplicatePersonsResponse)
async def merge_duplicate_persons(
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> MergeDuplicatePersonsResponse:
    """같은 이름의 인물이 여럿이면 하나로 병합(개인 공간 전용)."""
    result = await source.merge_duplicate_persons("personal")
    return MergeDuplicatePersonsResponse(merged=result["merged"])


@router.get("/person-items", response_model=BucketItemsResponse)
async def list_person_items(
    id: str,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    items = fill_thumbhashes(
        settings.sqlite_path, await source.person_items(space, id)
    )
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/places", response_model=PlacesResponse)
async def list_places(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> PlacesResponse:
    return PlacesResponse(space=space, places=await source.places(space))


@router.get("/place-items", response_model=BucketItemsResponse)
async def list_place_items(
    id: str,
    space: Space = Query("team"),
    limit: int | None = Query(None, ge=1, le=100),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """``limit`` (미리보기 카드) caps to a cheap single page."""
    items = fill_thumbhashes(
        settings.sqlite_path, await source.place_items(space, id, limit)
    )
    return BucketItemsResponse(space=space, day="", items=items)


@router.get("/videos", response_model=BucketItemsResponse)
async def list_videos(
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    """앨범 · 비디오 — 라이브러리 전체의 영상만(최신순)."""
    items = fill_thumbhashes(settings.sqlite_path, await source.videos(space))
    return BucketItemsResponse(space=space, day="", items=items)


# ---------------------------------------------- User albums (개인 공간 전용)
# 앨범은 로그인 사용자 본인의 개인 앨범(FotoTeam엔 앨범 API 없음). 라이브러리
# 셀렉터의 viewedOwner/zone과 무관하게 항상 personal로 취급한다(사람 렌즈와 동일).
_ALBUM_SPACE: Space = "personal"


@router.get("/albums", response_model=AlbumsResponse)
async def list_albums(
    source: PhotoSource = Depends(get_photo_source),
) -> AlbumsResponse:
    return AlbumsResponse(albums=await source.albums(_ALBUM_SPACE))


@router.get("/album-items", response_model=BucketItemsResponse)
async def list_album_items(
    id: str,
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> BucketItemsResponse:
    items = fill_thumbhashes(
        settings.sqlite_path, await source.album_items(_ALBUM_SPACE, id)
    )
    return BucketItemsResponse(space=_ALBUM_SPACE, day="", items=items)


@router.post("/albums", response_model=AlbumMutationResponse)
async def create_album(
    req: CreateAlbumRequest,
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> AlbumMutationResponse:
    """새 앨범 생성(비우면 빈 앨범, item_ids를 주면 담으며 생성)."""
    album = await source.create_album(_ALBUM_SPACE, req.name, req.item_ids)
    return AlbumMutationResponse(album=album, added=len(req.item_ids))


@router.post("/albums/add", response_model=AlbumMutationResponse)
async def add_to_album(
    req: AddToAlbumRequest,
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> AlbumMutationResponse:
    """기존 앨범에 사진 추가."""
    added = await source.add_to_album(_ALBUM_SPACE, req.album_id, req.item_ids)
    return AlbumMutationResponse(album=None, added=added)


@router.delete("/albums/{album_id}", response_model=AlbumMutationResponse)
async def delete_album(
    album_id: str,
    _session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> AlbumMutationResponse:
    """앨범 삭제(사진 자체는 그대로)."""
    await source.delete_album(_ALBUM_SPACE, album_id)
    return AlbumMutationResponse(album=None, added=0)


# ------------------------------------------------------------ file operations


@router.post("/ops/move-check", response_model=MoveCheckResponse)
async def op_move_check(
    req: MoveCheckRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> MoveCheckResponse:
    """Pre-flight: which selected items would collide by filename at the dest.
    The frontend calls this before a move/copy to raise the 충돌 처리 dialog."""
    _check_target_user(session, req.target_user)
    pairs = await source.conflicts(req.space, req.item_ids, req.dest_folder_id)
    return MoveCheckResponse(
        conflicts=[ConflictItem(item_id=i, filename=f) for i, f in pairs]
    )


@router.post("/ops/move", response_model=OperationResponse)
async def op_move(
    req: MoveRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    verb = "복사" if req.copy_mode else "이동"
    try:
        return await execute_move(
            source,
            settings.sqlite_path,
            user=session.account,
            req=req,
            on_progress=progress.callback(req.progress_key, verb),
        )
    finally:
        progress.clear(req.progress_key)


@router.post("/ops/delete", response_model=OperationResponse)
async def op_delete(
    req: DeleteRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    try:
        return await execute_delete(
            source,
            settings.sqlite_path,
            user=session.account,
            req=req,
            on_progress=progress.callback(req.progress_key, "삭제"),
        )
    finally:
        progress.clear(req.progress_key)


@router.post("/folders", response_model=OperationResponse)
async def op_create_folder(
    req: CreateFolderRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    _check_target_user(session, req.target_user)
    if req.space not in ("personal", "team"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="space는 personal 또는 team 이어야 합니다.",
        )
    return await execute_create_folder(
        source, settings.sqlite_path, user=session.account, req=req
    )


@router.get("/video")
async def stream_video(
    id: str,
    request: Request,
    space: Space = Query("team"),
    source: PhotoSource = Depends(get_photo_source),
) -> StreamingResponse:
    """Video playback proxy — Range passthrough so <video> seeking works."""
    upstream = await source.video_stream(space, id, request.headers.get("range"))
    # From here the upstream connection is checked out of the httpx pool; it is
    # only returned on aclose(). body()'s finally covers the normal path, but if
    # anything between here and the client consuming the stream raises/cancels
    # (header build, request cancellation), body() may never run — so guard the
    # setup and attach a BackgroundTask so the connection is always released.
    # (aclose() is idempotent, so a double close on the normal path is a no-op.)
    try:
        passthrough = {
            k: v
            for k, v in upstream.headers.items()
            if k.lower() in ("content-type", "content-length", "content-range")
        }
        passthrough.setdefault("Accept-Ranges", "bytes")

        async def body():
            try:
                async for chunk in upstream.aiter_bytes(64 * 1024):
                    yield chunk
            finally:
                await upstream.aclose()

        return StreamingResponse(
            body(),
            status_code=upstream.status_code,
            headers=passthrough,
            background=BackgroundTask(upstream.aclose),
        )
    except BaseException:
        await upstream.aclose()
        raise


@router.post("/ops/move-folders", response_model=OperationResponse)
async def op_move_folders(
    req: MoveFoldersRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    """폴더째(하위 포함) 이동/복사 — 여러 폴더 한 번에."""
    _check_target_user(session, req.target_user)
    verb = "복사" if req.copy_mode else "이동"
    try:
        return await execute_move_folders(
            source,
            settings.sqlite_path,
            user=session.account,
            req=req,
            on_progress=progress.callback(req.progress_key, f"폴더 {verb}"),
        )
    finally:
        progress.clear(req.progress_key)


@router.get("/folder-name-audit", response_model=FolderAuditResponse)
async def folder_name_audit(
    root: str | None = None,
    source: PhotoSource = Depends(get_photo_source),
) -> FolderAuditResponse:
    """root(경로형 폴더 id, 없으면 영역 루트) 하위를 재귀로 훑어 이름 규칙에
    어긋난 폴더(날짜부 밑줄)와 교정안을 반환. 1차 구역 전용."""
    return FolderAuditResponse(items=await source.audit_folder_names(root))


@router.post("/folders/rename", response_model=RenameFolderResponse)
async def rename_folder(
    req: RenameFolderRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> RenameFolderResponse:
    """폴더 이름 변경(제자리). 사진·썸네일은 그대로 유지된다."""
    _check_target_user(session, req.target_user)
    new_id, new_name = await source.rename_folder(
        req.space, req.folder_id, req.new_name
    )
    return RenameFolderResponse(id=new_id, name=new_name)


# --- 촬영일 교정 (파일에 실제 기록: EXIF + mtime) ---
def _gate_home_path(session: Session, path: str) -> None:
    """Only the session user's own home (writable by the container's uid) may be
    edited — never another user's home or the root-owned team share."""
    if not path.startswith(f"/homes/{session.account}/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 홈(1차 구역·내 사진)의 사진만 촬영일 교정이 가능합니다.",
        )


def _parse_user_date(s: str) -> datetime | None:
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _summarize(counter: Counter) -> CaptureFixResponse:
    ok = counter.get("ok", 0)
    failed = sum(v for k, v in counter.items() if k.startswith("failed") or k in ("not-found", "bad-date"))
    skipped = sum(v for k, v in counter.items() if k in ("no-date", "already-ok"))
    return CaptureFixResponse(ok=ok, skipped=skipped, failed=failed, details=dict(counter))


@router.get("/capture-audit", response_model=CaptureAuditResponse)
async def capture_audit(
    root: str,
    session: Session = Depends(get_current_session),
) -> CaptureAuditResponse:
    """root(홈 폴더 경로 id) 하위 미디어를 재귀 스캔해 현재 날짜(mtime)와
    파일명에서 추정한 촬영일을 반환(파일 무변경). 자동/수동 대상 분류."""
    _gate_home_path(session, root)
    rows = await asyncio.to_thread(capture_fix.scan_audit, root, 5000)
    # auto = 촬영일을 알아냈고 현재 표시값(mtime)과 달라 교정이 필요한 것.
    # manual = 촬영일 단서가 없는 것. (이미 맞는 건 둘 다 아님.)
    auto = sum(
        1
        for r in rows
        if r["detected"] and r["detected"][:10] != r["current"][:10]
    )
    manual = sum(1 for r in rows if not r["detected"])
    return CaptureAuditResponse(
        items=[CaptureAuditItem(**r) for r in rows],
        total=len(rows),
        auto=auto,
        manual=manual,
    )


def _run_auto(paths: list[str], cb) -> Counter:
    counter: Counter = Counter()
    total = len(paths)
    for i, p in enumerate(paths):
        counter[capture_fix.apply_auto(p)] += 1
        if cb:
            cb(i + 1, total)
    return counter


@router.post("/capture-fix", response_model=CaptureFixResponse)
async def capture_fix_auto(
    req: CaptureFixRequest,
    progress_key: str | None = Query(default=None, max_length=64),
    session: Session = Depends(get_current_session),
) -> CaptureFixResponse:
    """자동 감지분 적용: 각 파일을 EXIF(있으면 유지)→파일명 순으로 해석해
    JPEG은 EXIF 촬영일 + 전 포맷 mtime으로 기록."""
    for p in req.paths:
        _gate_home_path(session, p)
    cb = progress.callback(progress_key, "촬영일 교정")
    counter = await asyncio.to_thread(_run_auto, req.paths, cb)
    progress.clear(progress_key)
    # 내 사진(Synology) 타임라인은 백엔드 버킷 캐시(TTL 300s)를 거치므로, 파일
    # 날짜를 바꾼 뒤 캐시를 비워 다음 조회가 재인덱싱된 날짜를 즉시 반영하게 한다.
    invalidate_bucket_cache(session.sid)
    return _summarize(counter)


def _run_manual(items) -> Counter:
    counter: Counter = Counter()
    for it in items:
        dt = _parse_user_date(it.date)
        if dt is None:
            counter["bad-date"] += 1
            continue
        ok, msg = capture_fix.apply_one(it.path, dt)
        counter["ok" if ok else f"failed:{msg}"] += 1
    return counter


@router.post("/capture-fix-manual", response_model=CaptureFixResponse)
async def capture_fix_manual(
    req: CaptureFixManualRequest,
    session: Session = Depends(get_current_session),
) -> CaptureFixResponse:
    """사용자가 지정한 날짜를 파일에 기록(정보 없는 사진용)."""
    for it in req.items:
        _gate_home_path(session, it.path)
    counter = await asyncio.to_thread(_run_manual, req.items)
    invalidate_bucket_cache(session.sid)
    return _summarize(counter)


# --- 내 사진/공용(Synology Photos): 파일이 아니라 Synology 인덱스의 촬영시간을
# --- 직접 변경(SYNO.Foto.Browse.Item set). 파일 편집은 Synology가 재색인하지
# --- 않아 반영 안 되므로, 이미 색인된 사진은 이 경로로 교정한다.
def _exif_lookup(disk_root: str, filename: str):
    """EXIF capture datetime for a Foto item via the mount, or None. Guarded to
    the caller's home (disk_root already gated)."""
    from ..photos import capture_fix
    from ..photos.capture_date import read_exif_datetime

    disk = capture_fix.disk_path(f"{disk_root}/{filename}")
    if not disk or not os.path.isfile(disk):
        return None
    return read_exif_datetime(disk)


@router.get("/capture-audit-foto", response_model=CaptureAuditResponse)
async def capture_audit_foto(
    folder: str,
    space: Space = Query("personal"),
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> CaptureAuditResponse:
    """Foto 폴더 + 하위 전체(재귀) 사진의 현재 촬영일(Synology 인덱스)과 추정
    촬영일(파일명, 없으면 EXIF)을 반환. 파일 무변경(진단). 디스크 경로(EXIF용)는
    폴더 전체 경로명으로 서버가 계산(personal=/homes/<나>/Photos, team=/photo)."""
    base = "/photo" if space == "team" else f"/homes/{session.account}/Photos"
    folders = await source.capture_subtree(space, folder)
    # (item, folder_disk) 쌍으로 수집 — 하위 폴더 EXIF는 그 폴더 경로에서 읽는다.
    # 폴더별 수집을 유계 병렬로(순차 N+1이면 큰 트리에서 수십 초).
    sem = asyncio.Semaphore(6)

    async def collect(fid: str, fname: str):
        async with sem:
            return fname, await source.capture_items(space, fid)

    results = await asyncio.gather(*(collect(fid, fn) for fid, fn in folders))
    pairs: list[tuple[object, str]] = []
    for fname, items_of in results:
        fdisk = base + fname
        for it in items_of:
            pairs.append((it, fdisk))

    def probe(pair) -> CaptureAuditItem:
        it, fdisk = pair
        det = parse_from_filename(it.filename)
        src = "filename" if det else "none"
        if det is None:
            ex = _exif_lookup(fdisk, it.filename)
            if ex:
                det, src = ex, "exif"
        return CaptureAuditItem(
            path=it.id,
            filename=it.filename,
            current=it.taken_at,
            detected=det.isoformat() if det else None,
            source=src,
        )

    def build() -> list[CaptureAuditItem]:
        # EXIF 판독(파일당 디스크 IO)이 지배 비용 — 순차면 3천 장에 2분+
        # (2026-07-10 실측 146s). 스레드풀 병렬로 단축.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(probe, pairs))

    rows = await asyncio.to_thread(build)
    auto = sum(1 for r in rows if r.detected and r.detected[:10] != r.current[:10])
    manual = sum(1 for r in rows if not r.detected)
    return CaptureAuditResponse(items=rows, total=len(rows), auto=auto, manual=manual)


@router.post("/capture-fix-foto", response_model=CaptureFixResponse)
async def capture_fix_foto(
    req: CaptureFixFotoRequest,
    progress_key: str | None = Query(default=None, max_length=64),
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
) -> CaptureFixResponse:
    """지정한 촬영일을 Synology 인덱스에 기록(set). 자동/수동 모두 {id, date}."""
    if req.space not in ("personal", "team"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="space 오류"
        )
    cb = progress.callback(progress_key, "촬영일 교정")
    counter: Counter = Counter()
    total = len(req.items)
    for i, it in enumerate(req.items):
        dt = _parse_user_date(it.date)
        if dt is None:
            counter["bad-date"] += 1
        else:
            try:
                await source.set_item_time(req.space, it.path, int(dt.timestamp()))
                counter["ok"] += 1
            except Exception as exc:  # noqa: BLE001
                counter[f"failed:{type(exc).__name__}"] += 1
        if cb:
            cb(i + 1, total)
    progress.clear(progress_key)
    invalidate_bucket_cache(session.sid)
    return _summarize(counter)


@router.post("/folders/delete", response_model=OperationResponse)
async def op_remove_folder(
    req: RemoveFolderRequest,
    session: Session = Depends(get_current_session),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
) -> OperationResponse:
    """빈 폴더 삭제 (분할 뷰 정리) — 비어 있지 않으면 409."""
    _check_target_user(session, req.target_user)
    return await execute_remove_folder(
        source, settings.sqlite_path, user=session.account, req=req
    )


@router.get("/thumbnail")
async def get_thumbnail(
    id: str,
    request: Request,
    cache_key: str = "",
    space: Space = Query("team"),
    size: ThumbSize = Query("sm"),
    source: PhotoSource = Depends(get_photo_source),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_current_session),
) -> Response:
    # URL에 cache_key(내용 버전)가 들어 있어 내용이 바뀌면 URL이 바뀐다 → 사실상
    # 불변. 1년 immutable + ETag로 재방문 시 재다운로드/재검증을 없앤다.
    etag = f'"{id}-{cache_key}-{size}"'
    headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": etag,
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    # 서버측 디스크 캐시(mock 제외) — DSM 왕복을 줄인다(특히 느린 1차 구역
    # FileStation 썸네일·콜드 브라우저 캐시). 키에 계정을 넣어 접근 제어 보존.
    cache: ThumbCache | None = None
    key: str | None = None
    if not settings.mock_mode:
        cache = ThumbCache(
            os.path.join(os.path.dirname(settings.sqlite_path), "thumb-cache")
        )
        key = ThumbCache.key(session.account, space, id, cache_key, size)
        hit = cache.get(key)
        if hit is not None:
            return Response(content=hit, media_type=THUMB_MEDIA_TYPE, headers=headers)
    try:
        content, media_type = await source.thumbnail(space, id, cache_key, size)
    except DsmError as exc:
        # Session problems still need a 401 so the client re-auths; a genuinely
        # missing thumbnail (DSM 404 — Synology never generated a poster for
        # this item, common for videos) is a clean 404, not a 502. The frontend
        # <img> onError then shows its fallback tile without noisy errors.
        if exc.code in SESSION_INVALID_CODES:
            raise
        if exc.http_status == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "썸네일이 없습니다.") from exc
        raise
    if cache is not None and key is not None:
        cache.put(key, content)
    return Response(
        content=content,
        media_type=media_type,
        # Session-scoped images; safe to let the browser cache aggressively.
        headers=headers,
    )

"""DSM-backed photo source (SYNO.Foto.* / SYNO.FotoTeam.*).

⚠️ 실 NAS 미검증 (spec ch.7: Photos API는 비공식 문서만 존재).
아래 엔드포인트/파라미터/응답 필드는 커뮤니티 문서(zeichensatz/SynologyPhotosAPI,
N4S4/synology-api) 기준의 최선 추정이며, 실제 NAS 검증 단계(명세 13장)에서
반드시 확인·수정해야 한다. 검증 전까지 개발은 MOCK_MODE=true 로 진행한다.

검증 필요 항목:
- SYNO.Foto.Browse.Timeline `get` 의 존재 여부와 timeline_group_unit 파라미터,
  응답의 section/list 구조 (day별 item_count)
- SYNO.Foto.Browse.Item `list` 의 start_time/end_time epoch 필터 지원 여부
- additional 파라미터의 JSON 인코딩 방식 (["thumbnail","resolution"])
- 썸네일 바이너리 응답 (SYNO.Foto.Thumbnail `get` + type/size 파라미터)
- 파일 작업(이동/복사/삭제): Foto item id → 실제 파일 경로 매핑
  (Browse.Item `get` + additional=["folder"]) 후 FileStation CopyMove/Delete.
  FileStation 쪽은 공식 문서화된 API지만, 경로 매핑과 Photos 재인덱싱 지연은
  실 NAS에서 확인 필요 (spec ch.4 '두 경로 모두 검증').
- 휴지통 복원(undo delete): #recycle 경로 규칙 확인 필요.
"""

from __future__ import annotations

import asyncio
import json
import time as _time
from collections import Counter
from datetime import date, datetime, timedelta

from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..schemas import PhotoBucket, PhotoFolder, PhotoItem, PlacedItem
from .hashing import compute_hashes
from .source import Affected, DeleteOutcome, MoveOutcome

# Bucket cache: (sid, space) -> (monotonic_ts, buckets). Building buckets pages
# the entire library (~2s per 5000 items), so we cache the result briefly and
# invalidate on writes. Process-local; lost on restart (rebuilds on demand).
_BUCKET_CACHE: dict[tuple[str, str], tuple[float, list[PhotoBucket]]] = {}
_BUCKET_TTL = 300.0  # seconds
_PAGE = 5000


def invalidate_bucket_cache(sid: str, space: str | None = None) -> None:
    if space is None:
        for key in [k for k in _BUCKET_CACHE if k[0] == sid]:
            _BUCKET_CACHE.pop(key, None)
    else:
        _BUCKET_CACHE.pop((sid, space), None)


def _ns(space: str, api: str) -> str:
    """Map an API name into the right namespace for the space.

    Personal space uses SYNO.Foto.*, shared (team) space uses SYNO.FotoTeam.*
    with an otherwise identical surface — the namespace split is the single
    biggest trap in the unofficial Photos API.
    """
    if space == "team":
        return api.replace("SYNO.Foto.", "SYNO.FotoTeam.")
    return api


class DsmPhotoSource:
    """PhotoSource implementation talking to Synology Photos via the Web API."""

    def __init__(self, dsm: DsmClient, sid: str):
        self._dsm = dsm
        self._sid = sid

    async def buckets(self, space: str) -> list[PhotoBucket]:
        """Day buckets grouped in local (KST) time by paging the whole library.

        실 NAS 검증(DSM 7.2, 2026-07): SYNO.Foto.Browse.Timeline 의 일별 count 는
        UTC 계열로 그룹핑되어 우리가 쓰는 로컬(KST) 자정 경계 items() 와 날짜별
        개수가 어긋난다(사진 표시는 정확하나 헤더 count 불일치). 정확도를 위해
        Timeline 을 쓰지 않고 Browse.Item 을 전량 페이징하며 taken time 을 서버
        로컬 타임존으로 그룹핑한다 — buckets 와 items 가 동일 소스·동일 TZ 라
        개수가 정확히 일치한다. (배포 컨테이너 TZ=Asia/Seoul 전제 — docker 설정)

        비용: 라이브러리당 ~2s/5000장. 결과는 (sid,space)로 짧게 캐시하고
        쓰기 작업 시 무효화한다.
        """
        cache_key = (self._sid, space)
        cached = _BUCKET_CACHE.get(cache_key)
        if cached and (_time.monotonic() - cached[0]) < _BUCKET_TTL:
            return cached[1]

        counter: Counter[str] = Counter()
        offset = 0
        while True:
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"),
                "list",
                version=1,
                sid=self._sid,
                # additional 생략 → time 만 받아 페이로드 최소화.
                extra={"offset": offset, "limit": _PAGE},
            )
            items = data.get("list", [])
            for it in items:
                ts = it.get("time")
                if ts:
                    counter[date.fromtimestamp(ts).isoformat()] += 1
            if len(items) < _PAGE:
                break
            offset += _PAGE

        out = [
            PhotoBucket(day=day, count=count)
            for day, count in sorted(counter.items(), reverse=True)
        ]
        _BUCKET_CACHE[cache_key] = (_time.monotonic(), out)
        return out

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        d = date.fromisoformat(day)
        start = int(datetime(d.year, d.month, d.day).timestamp())
        end = int((datetime(d.year, d.month, d.day) + timedelta(days=1)).timestamp())
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "list",
            version=1,
            sid=self._sid,
            extra={
                "offset": 0,
                "limit": 1000,
                "start_time": start,
                "end_time": end,
                "sort_by": "takentime",
                "sort_direction": "asc",
                "additional": json.dumps(["thumbnail", "resolution"]),
            },
        )
        return [self._to_item(it) for it in data.get("list", [])]

    @staticmethod
    def _to_item(it: dict) -> PhotoItem:
        additional = it.get("additional", {})
        resolution = additional.get("resolution", {})
        thumb = additional.get("thumbnail", {})
        return PhotoItem(
            id=str(it.get("id")),
            filename=it.get("filename", ""),
            taken_at=datetime.fromtimestamp(it.get("time", 0)).isoformat(),
            width=int(resolution.get("width", 4)) or 4,
            height=int(resolution.get("height", 3)) or 3,
            size=it.get("filesize"),
            cache_key=thumb.get("cache_key", ""),
            placeholder_color=None,  # thumbhash lands with photo_cache (phase 2)
            folder=None,
        )

    async def folders(self) -> list[PhotoFolder]:
        out: list[PhotoFolder] = []
        for space in ("team", "personal"):
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Folder"),
                "list",
                sid=self._sid,
                extra={"offset": 0, "limit": 200},
            )
            for f in data.get("list", []):
                out.append(
                    PhotoFolder(
                        id=str(f.get("id")), name=f.get("name", ""), space=space
                    )
                )
        return out

    async def folder_items(self, folder_id: str) -> list[PhotoItem]:
        # folder_id 필터는 실 NAS에서 동작 확인됨(2026-07). 공유/개인 구분은
        # folders()가 space를 붙여 주므로, 여기서는 team 기준으로 조회한다.
        # (개인 공간 폴더 뷰는 space 인지가 필요 — 후속.)
        data = await self._dsm.call(
            "SYNO.FotoTeam.Browse.Item",
            "list",
            version=1,
            sid=self._sid,
            extra={
                "folder_id": int(folder_id),
                "offset": 0,
                "limit": 1000,
                "additional": json.dumps(["thumbnail", "resolution"]),
            },
        )
        return [self._to_item(it) for it in data.get("list", [])]

    async def members(self) -> list[str]:
        # 관리자 전용: /homes 하위 폴더명 = 구성원 계정 (user home 서비스 전제).
        data = await self._dsm.call(
            "SYNO.FileStation.List",
            "list",
            sid=self._sid,
            extra={"folder_path": "/homes", "limit": 200},
        )
        return sorted(
            f.get("name", "")
            for f in data.get("files", [])
            if f.get("isdir") and not f.get("name", "").startswith("@")
        )

    async def thumbnail(
        self, space: str, item_id: str, cache_key: str, size: str
    ) -> tuple[bytes, str]:
        return await self._dsm.fetch_binary(
            _ns(space, "SYNO.Foto.Thumbnail"),
            "get",
            sid=self._sid,
            extra={
                "id": item_id,
                "cache_key": cache_key,
                "type": "unit",
                "size": size,
            },
        )

    async def item_hashes(self, space: str, item: PhotoItem) -> tuple[str, str]:
        """Real hashes over the small thumbnail (D절: 원본 전송 회피).

        SHA-256 over thumbnail bytes(동일 원본 → 동일 Synology 썸네일 전제,
        실 NAS 검증 항목), pHash over the decoded pixels.
        """
        data, _ = await self.thumbnail(space, item.id, item.cache_key, "sm")
        return compute_hashes(data)

    # ------------------------------------------------------------ write side
    #
    # 실 NAS 검증(DSM 7.2, 2026-07):
    # - item→경로: Browse.Item get + additional=["folder"] → prefix+folder+name
    # - 이동/복사: FileStation.CopyMove start→status 폴링(remove_src=이동/복사)
    # - 삭제: photo 공유폴더 휴지통 비활성이라 Delete는 영구삭제 → 앱 관리
    #   휴지통 폴더(/photo/#trash/<time_ns>/)로 CopyMove. 복원은 역이동.
    # - 복사 취소(undo)만 실제 Delete(영구) — 방금 만든 사본이므로 안전.
    # 재인덱싱 지연으로 buckets 캐시는 쓰기 후 무효화한다.
    TRASH_ROOT = "/photo/#trash"

    def _share_prefix(self, space: str) -> str:
        if space == "team":
            return "/photo"
        # 개인 공간(SYNO.Foto)의 파일시스템 프리픽스는 실 NAS 미검증.
        raise DsmError(
            100, "개인 공간 파일 작업은 아직 지원되지 않습니다 (경로 검증 필요)."
        )

    async def _copymove(
        self, src_paths: list[str], dest_dir: str, *, remove_src: bool
    ) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.CopyMove",
            "start",
            version=3,
            sid=self._sid,
            extra={
                "path": json.dumps(src_paths),
                "dest_folder_path": dest_dir,
                "remove_src": "true" if remove_src else "false",
                "overwrite": "false",
            },
        )
        await self._poll_task("SYNO.FileStation.CopyMove", 3, data.get("taskid"))

    async def _delete_paths(self, paths: list[str]) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.Delete",
            "start",
            version=2,
            sid=self._sid,
            extra={"path": json.dumps(paths)},
        )
        await self._poll_task("SYNO.FileStation.Delete", 2, data.get("taskid"))

    async def _poll_task(self, api: str, version: int, taskid: str | None) -> None:
        if not taskid:
            raise DsmError(100, "파일 작업 태스크를 시작하지 못했습니다.")
        for _ in range(120):  # ≤ 60s
            status = await self._dsm.call(
                api, "status", version=version, sid=self._sid,
                extra={"taskid": taskid},
            )
            if status.get("finished"):
                return
            await asyncio.sleep(0.5)
        raise DsmError(100, "파일 작업이 제한 시간 안에 끝나지 않았습니다.")

    async def _item_meta(
        self, space: str, item_ids: list[str]
    ) -> dict[str, dict]:
        """id → {path, folder_id, day} for the given items."""
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "get",
            version=1,
            sid=self._sid,
            extra={
                "id": json.dumps([int(i) for i in item_ids]),
                "additional": json.dumps(["folder"]),
            },
        )
        prefix = self._share_prefix(space)
        out: dict[str, dict] = {}
        for it in data.get("list", []):
            folder = it.get("additional", {}).get("folder") or {}
            folder_name = folder.get("name") if isinstance(folder, dict) else folder
            filename = it.get("filename", "")
            day = date.fromtimestamp(it.get("time", 0)).isoformat()
            out[str(it.get("id"))] = {
                "path": f"{prefix}{folder_name}/{filename}".replace("//", "/"),
                "filename": filename,
                "folder_id": str(it.get("folder_id", "")),
                "day": day,
            }
        return out

    async def _dest_dir(self, dest_folder_id: str) -> tuple[str, str]:
        """dest folder id → (absolute dir path, space)."""
        for f in await self.folders():
            if f.id == dest_folder_id:
                prefix = self._share_prefix(f.space)
                return f"{prefix}{f.name}".replace("//", "/").rstrip("/") or prefix, f.space
        raise DsmError(100, "대상 폴더를 찾을 수 없습니다.")

    async def move(
        self, space: str, item_ids: list[str], dest_folder_id: str, copy: bool
    ) -> MoveOutcome:
        metas = await self._item_meta(space, item_ids)
        dest_dir, dest_space = await self._dest_dir(dest_folder_id)
        outcome = MoveOutcome(dest_space=dest_space)
        affected: set[tuple[str, str]] = set()
        src_paths = [metas[i]["path"] for i in item_ids if i in metas]

        await self._copymove(src_paths, dest_dir, remove_src=not copy)

        for item_id in item_ids:
            m = metas.get(item_id)
            if not m:
                continue
            day = m["day"]
            dest_path = f"{dest_dir}/{m['filename']}"
            affected.add((space, day))
            affected.add((dest_space, day))
            if copy:
                outcome.created_ids.append(dest_path)  # DSM: path, not item id
            else:
                outcome.moved.append(
                    PlacedItem(
                        id=item_id, space=space, folder_id=m["folder_id"], day=day,
                        src_path=m["path"], trash_path=dest_path,  # current location
                    )
                )
        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

    async def delete(self, space: str, item_ids: list[str]) -> DeleteOutcome:
        metas = await self._item_meta(space, item_ids)
        outcome = DeleteOutcome()
        affected: set[tuple[str, str]] = set()
        # One unique trash subfolder per delete op (avoids filename collisions).
        # 't' prefix: DSM rejects all-numeric folder names (code 400).
        trash_dir = f"{self.TRASH_ROOT}/t{_time.time_ns()}"
        await self._ensure_dir(trash_dir)
        src_paths = [metas[i]["path"] for i in item_ids if i in metas]
        await self._copymove(src_paths, trash_dir, remove_src=True)

        for item_id in item_ids:
            m = metas.get(item_id)
            if not m:
                continue
            affected.add((space, m["day"]))
            outcome.deleted.append(
                PlacedItem(
                    id=item_id, space=space, folder_id=m["folder_id"], day=m["day"],
                    src_path=m["path"], trash_path=f"{trash_dir}/{m['filename']}",
                )
            )
        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

    async def _reverse(self, placements: list[PlacedItem]) -> Affected:
        """Move each item from its current (trash_path) location back to src."""
        affected: set[tuple[str, str]] = set()
        for p in placements:
            if not p.src_path or not p.trash_path:
                continue
            dest_dir = p.src_path.rsplit("/", 1)[0]
            await self._copymove([p.trash_path], dest_dir, remove_src=True)
            affected.add((p.space, p.day))
        self._invalidate(affected)
        return sorted(affected)

    async def place(self, placements: list[PlacedItem]) -> Affected:
        return await self._reverse(placements)  # undo move

    async def restore(self, placements: list[PlacedItem]) -> Affected:
        return await self._reverse(placements)  # undo delete (from app trash)

    async def remove_items(self, item_ids: list[str]) -> Affected:
        # undo copy: item_ids are actually the created copies' absolute paths.
        await self._delete_paths(item_ids)
        invalidate_bucket_cache(self._sid)  # day unknown per path — clear all
        return []

    async def _ensure_dir(self, path: str) -> None:
        # Create each level below the share root (/photo). Nested one-shot
        # creation with force_parent fails on '#'-prefixed segments (code 1002),
        # so build the path level by level; existing levels error out harmlessly.
        parts = path.split("/")  # ['', 'photo', '#trash', '<id>']
        for i in range(3, len(parts) + 1):
            parent = "/".join(parts[: i - 1])
            name = parts[i - 1]
            try:
                await self._dsm.call(
                    "SYNO.FileStation.CreateFolder", "create", version=2,
                    sid=self._sid, extra={"folder_path": parent, "name": name},
                )
            except DsmError:
                pass  # already exists → fine

    async def create_folder(self, space: str, name: str) -> PhotoFolder:
        prefix = self._share_prefix(space)
        await self._dsm.call(
            "SYNO.FileStation.CreateFolder", "create", version=2, sid=self._sid,
            extra={"folder_path": prefix, "name": name},
        )
        # Re-resolve via Photos so the new folder carries a Photos folder id
        # (FileStation create returns a filesystem path, not a Foto id).
        for f in await self.folders():
            if f.space == space and f.name.rstrip("/").endswith(name):
                return f
        return PhotoFolder(id=f"{prefix}/{name}", name=f"/{name}", space=space)

    async def remove_folder(self, folder_id: str) -> bool:
        try:
            dest_dir, _ = await self._dest_dir(folder_id)
        except DsmError:
            return False
        await self._delete_paths([dest_dir])
        return True

    def _invalidate(self, affected: set[tuple[str, str]]) -> None:
        for space, _ in affected:
            invalidate_bucket_cache(self._sid, space)

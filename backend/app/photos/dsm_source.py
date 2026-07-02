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

import json
from datetime import date, datetime, timedelta

from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..schemas import PhotoBucket, PhotoFolder, PhotoItem, PlacedItem
from .hashing import compute_hashes
from .source import Affected, DeleteOutcome, MoveOutcome


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
        # 검증 필요: Timeline API 응답 구조. Synology Photos 웹 UI 자체가
        # count-first 타임라인을 쓰므로 대응 API가 존재한다.
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Timeline"),
            "get",
            sid=self._sid,
            extra={"timeline_group_unit": "day"},
        )
        sections = data.get("section") or data.get("list") or []
        out: list[PhotoBucket] = []
        for s in sections:
            year, month = s.get("year"), s.get("month")
            day = s.get("day")
            count = int(s.get("item_count", 0))
            if not (year and month and day) or count <= 0:
                continue
            out.append(
                PhotoBucket(day=f"{year:04d}-{month:02d}-{day:02d}", count=count)
            )
        out.sort(key=lambda b: b.day, reverse=True)
        return out

    async def items(self, space: str, day: str) -> list[PhotoItem]:
        d = date.fromisoformat(day)
        start = int(datetime(d.year, d.month, d.day).timestamp())
        end = int((datetime(d.year, d.month, d.day) + timedelta(days=1)).timestamp())
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "list",
            sid=self._sid,
            extra={
                "offset": 0,
                "limit": 1000,
                "start_time": start,
                "end_time": end,
                "sort_by": "takentime",
                "sort_direction": "asc",
                # 검증 필요: additional 은 JSON 배열 문자열로 전달해야 한다.
                "additional": json.dumps(["thumbnail", "resolution"]),
            },
        )
        out: list[PhotoItem] = []
        for it in data.get("list", []):
            additional = it.get("additional", {})
            resolution = additional.get("resolution", {})
            thumb = additional.get("thumbnail", {})
            taken = datetime.fromtimestamp(it.get("time", start)).isoformat()
            out.append(
                PhotoItem(
                    id=str(it.get("id")),
                    filename=it.get("filename", ""),
                    taken_at=taken,
                    width=int(resolution.get("width", 4)) or 4,
                    height=int(resolution.get("height", 3)) or 3,
                    size=it.get("filesize"),
                    cache_key=thumb.get("cache_key", ""),
                    placeholder_color=None,  # thumbhash lands with photo_cache (phase 2)
                    folder=None,
                )
            )
        return out

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
        # 검증 필요: Browse.Item list 의 folder_id 필터. 공유/개인 네임스페이스는
        # folder_id 프리픽스로 구분할 수 없어 실 NAS에서 규칙 확인 필요.
        raise DsmError(100, "폴더 내용 조회는 실 NAS 검증 후 활성화됩니다.")

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
    # 구현 전략(spec ch.4, 실 NAS 검증 단계에서 활성화):
    # 1) Foto item id → 파일 경로: Browse.Item `get` + additional=["folder"]
    # 2) 이동/복사: SYNO.FileStation.CopyMove `start` → `status` 폴링(taskid,
    #    finished 필드) — FileStation 쪽은 공식 문서화된 API
    # 3) 삭제: SYNO.FileStation.Delete `start` → 폴링 (#recycle 활성 전제)
    # 4) 이동 후 Photos 재인덱싱 지연 → 프론트는 낙관적 갱신 + 재조회 전제
    # 검증 전에는 명확한 오류를 던져 MOCK_MODE 개발과 혼동을 막는다.

    async def move(
        self, item_ids: list[str], dest_folder_id: str, copy: bool
    ) -> MoveOutcome:
        # 검증 필요: PhotoFolder.name 이 실제 파일시스템 경로인지(현재 가정),
        # cross-space 이동 시 재인덱싱 지연.
        raise DsmError(100, "DSM 파일 이동은 실 NAS 검증 후 활성화됩니다 (MOCK_MODE로 개발).")

    async def delete(self, item_ids: list[str]) -> DeleteOutcome:
        raise DsmError(100, "DSM 삭제는 실 NAS 검증 후 활성화됩니다 (MOCK_MODE로 개발).")

    async def place(self, placements: list[PlacedItem]) -> Affected:
        raise DsmError(100, "DSM 되돌리기는 실 NAS 검증 후 활성화됩니다.")

    async def restore(self, placements: list[PlacedItem]) -> Affected:
        raise DsmError(100, "DSM 휴지통 복원은 실 NAS 검증 후 활성화됩니다.")

    async def remove_items(self, item_ids: list[str]) -> Affected:
        raise DsmError(100, "DSM 복사 취소는 실 NAS 검증 후 활성화됩니다.")

    async def create_folder(self, space: str, name: str) -> PhotoFolder:
        raise DsmError(100, "DSM 폴더 생성은 실 NAS 검증 후 활성화됩니다.")

    async def remove_folder(self, folder_id: str) -> bool:
        raise DsmError(100, "DSM 폴더 삭제는 실 NAS 검증 후 활성화됩니다.")

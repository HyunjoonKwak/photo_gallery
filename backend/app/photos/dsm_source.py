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
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from ..dsm.client import DsmClient
from ..schemas import PhotoBucket, PhotoFolder, PhotoItem


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

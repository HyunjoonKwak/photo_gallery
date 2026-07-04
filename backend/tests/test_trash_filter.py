"""Photos가 /photo/#trash까지 인덱싱하므로 목록 API들이 휴지통 아이템을
제외하는지 검증한다 (2026-07-04 실 NAS 보고: 삭제 사진이 공용 타임라인 노출)."""

import time as _time

import pytest

from app.photos.dsm_source import DsmPhotoSource


class _RoutingDsm:
    """(api, method, 주요 파라미터) 조합별로 준비된 응답을 돌려주는 스텁."""

    def __init__(self, routes):
        self.routes = routes  # list[(matcher(extra) -> bool, api, data)]
        self.calls = []

    async def call(self, api, method, **kwargs):
        extra = kwargs.get("extra", {}) or {}
        self.calls.append((api, method, extra))
        for match_api, matcher, data in self.routes:
            if api == match_api and matcher(extra):
                return data
        return {"list": []}


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"  # 모듈 캐시(sid 키) 충돌 방지


async def test_trash_item_ids_collects_ids_under_trash_tree():
    dsm = _RoutingDsm(
        [
            (
                "SYNO.FotoTeam.Browse.Folder",
                lambda e: e.get("id") == 0,
                {"list": [{"id": 10, "name": "/#trash"}, {"id": 2, "name": "/가족앨범"}]},
            ),
            (
                "SYNO.FotoTeam.Browse.Folder",
                lambda e: e.get("id") == 10,
                {"list": [{"id": 11, "name": "/#trash/t123"}]},
            ),
            (
                "SYNO.FotoTeam.Browse.Item",
                lambda e: e.get("folder_id") == 11,
                {"list": [{"id": 901}, {"id": 902}]},
            ),
        ]
    )
    src = DsmPhotoSource(dsm, _sid())
    assert await src._trash_item_ids("team") == {"901", "902"}


async def test_trash_ids_empty_for_personal_space():
    src = DsmPhotoSource(_RoutingDsm([]), _sid())
    assert await src._trash_item_ids("personal") == frozenset()


async def test_buckets_exclude_trashed_items(monkeypatch):
    ts = int(_time.time())
    dsm = _RoutingDsm(
        [
            (
                "SYNO.FotoTeam.Browse.Item",
                lambda e: "folder_id" not in e,
                {"list": [{"id": 900, "time": ts}, {"id": 901, "time": ts}]},
            ),
        ]
    )
    src = DsmPhotoSource(dsm, _sid())

    async def fake_trash(space="team"):
        return frozenset({"901"})

    monkeypatch.setattr(src, "_trash_item_ids", fake_trash)
    buckets = await src.buckets("team")
    assert len(buckets) == 1 and buckets[0].count == 1


async def test_items_exclude_trashed_items(monkeypatch):
    ts = int(_time.time())
    dsm = _RoutingDsm(
        [
            (
                "SYNO.FotoTeam.Browse.Item",
                lambda e: "start_time" in e,
                {"list": [{"id": 900, "time": ts}, {"id": 901, "time": ts}]},
            ),
        ]
    )
    src = DsmPhotoSource(dsm, _sid())

    async def fake_trash(space="team"):
        return frozenset({"901"})

    monkeypatch.setattr(src, "_trash_item_ids", fake_trash)
    from datetime import date

    items = await src.items("team", date.fromtimestamp(ts).isoformat())
    assert [i.id for i in items] == ["900"]


async def test_folder_tree_hides_system_folders(monkeypatch):
    src = DsmPhotoSource(_RoutingDsm([]), _sid())

    async def fake_children(space, parent_id):
        if space == "team":
            return [{"id": 10, "name": "/#trash"}, {"id": 2, "name": "/가족앨범"}]
        return []

    monkeypatch.setattr(src, "_list_children", fake_children)
    folders = await src.folders()
    assert [f.name for f in folders] == ["/가족앨범"]

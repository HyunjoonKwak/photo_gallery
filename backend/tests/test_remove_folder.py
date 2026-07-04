"""Unit tests for DsmPhotoSource.remove_folder's filesystem emptiness check.

The check must use FileStation (filesystem truth), not the Photos index —
the index lags in both directions (see remove_folder docstring).
"""

import time as _time

import pytest

from app.photos import dsm_source
from app.photos.dsm_source import DsmPhotoSource


class _StubDsm:
    """Answers FileStation.List with a fixed file listing."""

    def __init__(self, files: list[dict]):
        self.files = files
        self.calls: list[tuple] = []

    async def call(self, api, method, **kwargs):
        self.calls.append((api, method, kwargs))
        return {"files": self.files}


@pytest.fixture()
def make_source(monkeypatch):
    def make(files: list[dict]):
        # 모듈 전역 tombstone 맵 오염 방지 — 테스트마다 고유 sid.
        sid = f"sid-{_time.monotonic_ns()}"
        src = DsmPhotoSource(_StubDsm(files), sid)
        deleted: list[str] = []

        async def _dest_dir(folder_id):
            return "/photo/빈폴더", "team"

        async def _delete_paths(paths):
            deleted.extend(paths)

        monkeypatch.setattr(src, "_dest_dir", _dest_dir)
        monkeypatch.setattr(src, "_delete_paths", _delete_paths)
        return src, deleted

    return make


async def test_folder_with_only_system_droppings_is_removed(make_source):
    src, deleted = make_source(
        [{"name": "@eaDir"}, {"name": ".DS_Store"}, {"name": "Thumbs.db"}]
    )
    assert await src.remove_folder("123") is True
    assert deleted == ["/photo/빈폴더"]


async def test_truly_empty_folder_is_removed(make_source):
    src, deleted = make_source([])
    assert await src.remove_folder("123") is True
    assert deleted == ["/photo/빈폴더"]


async def test_folder_with_a_real_file_is_kept(make_source):
    src, deleted = make_source([{"name": "IMG_0001.jpg"}])
    assert await src.remove_folder("123") is False
    assert deleted == []


async def test_folder_with_a_subfolder_is_kept(make_source):
    src, deleted = make_source([{"name": "하위폴더", "isdir": True}])
    assert await src.remove_folder("123") is False
    assert deleted == []


async def test_checks_filesystem_not_photos_index(make_source):
    src, _ = make_source([])
    await src.remove_folder("123")
    apis = [c[0] for c in src._dsm.calls]
    assert apis == ["SYNO.FileStation.List"]


async def test_removed_folder_is_tombstoned_and_hidden_from_tree(
    make_source, monkeypatch
):
    """삭제 성공 후, Photos 인덱스가 여전히 그 폴더를 반환해도 트리에서 숨긴다
    (2026-07-04 실 NAS 보고: 삭제한 빈 폴더가 좌측 트리에 계속 보임)."""
    src, _ = make_source([])
    await src.remove_folder("123")
    assert "123" in dsm_source._tombstoned_folders(src._sid)

    # Photos가 아직 삭제된 폴더(id=123)를 반환하는 상황을 흉내낸다.
    async def fake_children(space, parent_id):
        if space == "team":
            return [{"id": 123, "name": "/빈폴더"}, {"id": 2, "name": "/가족앨범"}]
        return []

    monkeypatch.setattr(src, "_list_children", fake_children)
    folders = await src.folders()
    assert [f.name for f in folders] == ["/가족앨범"]


async def test_tombstone_expires_after_ttl(make_source, monkeypatch):
    src, _ = make_source([])
    await src.remove_folder("123")
    # TTL 경과를 흉내: 기록 시각을 과거로 밀어 만료시킨다.
    entries = dsm_source._REMOVED_FOLDERS[src._sid]
    entries["123"] -= dsm_source._REMOVED_FOLDER_TTL + 1
    assert "123" not in dsm_source._tombstoned_folders(src._sid)

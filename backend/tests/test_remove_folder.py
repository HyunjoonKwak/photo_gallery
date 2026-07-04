"""Unit tests for DsmPhotoSource.remove_folder's filesystem emptiness check.

The check must use FileStation (filesystem truth), not the Photos index —
the index lags in both directions (see remove_folder docstring).
"""

import pytest

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
        src = DsmPhotoSource(_StubDsm(files), "sid-test")
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

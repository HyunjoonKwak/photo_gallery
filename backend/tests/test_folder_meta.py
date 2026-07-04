"""invalidate_folder_cache가 폴더 경로맵(_FOLDER_META)을 지우면 쓰기 직후
중첩 폴더 재조회가 '경로 캐시 없음'으로 실패한다 — 새 폴더/이동 결과가
새로고침 전엔 안 보이던 원인(2026-07-05 실 NAS 보고). 맵 보존을 검증한다."""

import time as _time

import pytest

from app.photos import dsm_source
from app.photos.dsm_source import DsmPhotoSource, invalidate_folder_cache


class _FolderListDsm:
    """Browse.Folder list 에 부모별 자식 목록을 돌려주는 스텁."""

    def __init__(self, children_by_parent: dict[int, list[dict]]):
        self.children_by_parent = children_by_parent

    async def call(self, api, method, **kwargs):
        if method == "list" and "Browse.Folder" in api:
            pid = kwargs["extra"]["id"]
            return {"list": self.children_by_parent.get(pid, [])}
        return {"list": []}


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_nested_folders_resolve_after_write_invalidation():
    dsm = _FolderListDsm(
        {
            0: [{"id": 2, "name": "/가족앨범"}],
            2: [{"id": 5, "name": "/가족앨범/2025"}],
        }
    )
    src = DsmPhotoSource(dsm, _sid())

    # 최상위 → 가족앨범(2) 탐색: 메타에 2번 폴더 경로가 채워진다.
    top = await src.folders(None)
    assert any(f.id == "2" for f in top)
    children = await src.folders("2")
    assert [f.id for f in children] == ["5"]

    # 폴더 생성/이동 등이 부르는 무효화 — 이후에도 folders("2")가 성공해야 한다.
    invalidate_folder_cache(src._sid)
    again = await src.folders("2")  # 예전엔 여기서 DsmError('경로 캐시 없음')
    assert [f.id for f in again] == ["5"]


async def test_invalidation_still_clears_top_listing_cache():
    dsm = _FolderListDsm({0: [{"id": 2, "name": "/가족앨범"}]})
    src = DsmPhotoSource(dsm, _sid())
    await src.folders(None)
    assert src._sid in dsm_source._TOP_FOLDER_CACHE
    invalidate_folder_cache(src._sid)
    assert src._sid not in dsm_source._TOP_FOLDER_CACHE

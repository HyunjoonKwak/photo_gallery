"""폴더 배지 카운트의 재귀(하위 전체) 합산 검증.

직계 자식이 폴더뿐인 중간 폴더(연도 폴더 등)의 배지가 0장으로 나오던 회귀
(2026-08-13 보고) 방지 — folder_count는 서브트리 전체 사진·동영상 수여야 한다.
"""

import time as _time

from app.photos import capture_fix
from app.photos.dsm_source import DsmPhotoSource
from app.photos.homes_source import _count_media_on_disk


# ------------------------------------------------- 마운트 직접 카운트(homes/zone)

def test_disk_count_recurses_into_subfolders(tmp_path):
    (tmp_path / "sub" / "nested").mkdir(parents=True)
    (tmp_path / "sub" / "a.jpg").write_bytes(b"x")
    (tmp_path / "sub" / "nested" / "b.mp4").write_bytes(b"x")
    # 시스템 폴더(@eaDir 썸네일, #recycle)와 비미디어 파일은 제외돼야 한다.
    (tmp_path / "@eaDir").mkdir()
    (tmp_path / "@eaDir" / "SYNOPHOTO_THUMB_XL.jpg").write_bytes(b"x")
    (tmp_path / "#recycle").mkdir()
    (tmp_path / "#recycle" / "c.jpg").write_bytes(b"x")
    (tmp_path / "note.txt").write_bytes(b"x")
    assert _count_media_on_disk(str(tmp_path)) == 2


def test_disk_count_direct_files_still_counted(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.jpeg").write_bytes(b"x")
    assert _count_media_on_disk(str(tmp_path)) == 2


def test_disk_count_missing_dir_returns_none(tmp_path):
    # 접근 불가/부재 → None (API 폴백 신호) — 0으로 오인하면 안 된다.
    assert _count_media_on_disk(str(tmp_path / "없는폴더")) is None


# ------------------------------------------------- DSM Foto 폴더(가족/내 사진)

class _TreeDsm:
    """Browse.Folder list + Browse.Item count 스텁.

    team(FotoTeam)과 personal(Foto)을 구분해 응답 — folders(None)이 두 공간을
    같이 훑을 때 메타 공간이 뒤섞이지 않게 한다.
    """

    def __init__(self, children: dict[int, list[dict]], counts: dict[int, int]):
        self.children = children
        self.counts = counts

    async def call(self, api, method, **kwargs):
        team = "FotoTeam" in api
        if method == "list" and "Browse.Folder" in api:
            pid = kwargs["extra"]["id"]
            return {"list": self.children.get(pid, []) if team else []}
        if method == "count" and "Browse.Item" in api:
            fid = kwargs["extra"]["folder_id"]
            return {"count": self.counts.get(fid, 0) if team else 0}
        return {"list": []}


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_dsm_folder_count_sums_subtree(monkeypatch):
    # 마운트 미설정 환경(API 폴백) — 서브트리 폴더별 count 합산이어야 한다.
    monkeypatch.setattr(capture_fix, "_MOUNT_TEAM", "")
    monkeypatch.setattr(capture_fix, "_MOUNT", "")
    dsm = _TreeDsm(
        children={
            0: [{"id": 2, "name": "/앨범"}],
            2: [{"id": 5, "name": "/앨범/2024"}, {"id": 6, "name": "/앨범/2025"}],
        },
        counts={2: 0, 5: 3, 6: 4},  # 직속 사진은 하위 폴더에만 있다
    )
    src = DsmPhotoSource(dsm, _sid())
    # 메타(공간/경로) 캐시 채우기 — 배지는 UI가 폴더 목록을 탐색한 뒤 요청된다.
    await src.folders(None)
    await src.folders("2")
    assert await src.folder_count("2") == 7
    assert await src.folder_count("5") == 3


async def test_dsm_folder_count_prefers_team_mount(tmp_path, monkeypatch):
    # 마운트가 있으면 DSM 왕복 없이 디스크에서 재귀 카운트.
    monkeypatch.setattr(capture_fix, "_MOUNT_TEAM", str(tmp_path))
    (tmp_path / "앨범" / "2024").mkdir(parents=True)
    (tmp_path / "앨범" / "2024" / "a.jpg").write_bytes(b"x")
    (tmp_path / "앨범" / "2024" / "b.heic").write_bytes(b"x")
    dsm = _TreeDsm(children={0: [{"id": 2, "name": "/앨범"}]}, counts={})
    src = DsmPhotoSource(dsm, _sid())
    await src.folders(None)
    assert await src.folder_count("2") == 2

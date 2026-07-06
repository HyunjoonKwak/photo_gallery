"""사람(얼굴 그룹) 커버 썸네일 파싱 — 실 NAS(DSM 7.2) raw 응답 기준.

2026-07 실 NAS 확인: Person list 응답에서 커버 사진 id는 top-level `cover`에
오고, 썸네일 cache_key는 additional.thumbnail.cache_key. 예전엔 존재하지 않는
additional.thumbnail.unit_id를 읽어 cover_item_id가 항상 None → 사람 탭에
👤 placeholder만 떴다(사용자 보고)."""

import time as _time

from app.photos.dsm_source import DsmPhotoSource


class _StubDsm:
    def __init__(self, data):
        self.data = data

    async def call(self, api, method, **kwargs):
        return self.data


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_person_cover_from_top_level_cover_field():
    dsm = _StubDsm(
        {
            "list": [
                {
                    "id": 2408,
                    "name": "",
                    "item_count": 843,
                    "show": True,
                    "cover": 10860,
                    "additional": {"thumbnail": {"cache_key": "78112_1762208160"}},
                }
            ]
        }
    )
    persons = await DsmPhotoSource(dsm, _sid()).persons("personal")
    assert len(persons) == 1
    p = persons[0]
    assert p.cover_item_id == "10860"  # top-level `cover`, not unit_id
    assert p.cover_cache_key == "78112_1762208160"
    assert p.item_count == 843


async def test_person_cover_falls_back_to_unit_id():
    """구버전 호환: cover가 없고 unit_id만 있는 경우."""
    dsm = _StubDsm(
        {
            "list": [
                {
                    "id": 5,
                    "name": "지민",
                    "item_count": 12,
                    "show": True,
                    "additional": {"thumbnail": {"unit_id": 777, "cache_key": "777_1"}},
                }
            ]
        }
    )
    persons = await DsmPhotoSource(dsm, _sid()).persons("team")
    assert persons[0].cover_item_id == "777"


async def test_hidden_person_group_skipped():
    dsm = _StubDsm(
        {
            "list": [
                {"id": 1, "name": "", "cover": 100, "show": False, "additional": {}},
            ]
        }
    )
    assert await DsmPhotoSource(dsm, _sid()).persons("personal") == []

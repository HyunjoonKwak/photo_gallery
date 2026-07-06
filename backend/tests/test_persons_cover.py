"""사람(얼굴 그룹) 커버 썸네일 파싱 — 실 NAS(DSM 7.2) raw 응답 기준.

2026-07 실 NAS 확인: 썸네일 프록시는 type=unit + id=<unit id>로 동작하고,
사람 커버의 unit id는 cache_key 접두어("<unit_id>_<mtime>")에 들어 있다.
top-level `cover`(=item id)는 이 unit과 달라 그대로 넘기면 썸네일이 404가
난다(사용자 보고: 처음엔 unit_id 부재로 👤, cover를 넘기니 깨진 이미지).
따라서 cache_key 접두어를 커버 id로 쓴다."""

import time as _time

from app.photos.dsm_source import DsmPhotoSource


class _StubDsm:
    def __init__(self, data):
        self.data = data

    async def call(self, api, method, **kwargs):
        return self.data


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_person_cover_uses_cache_key_prefix_as_unit_id():
    """cache_key 접두어(78112)가 실제 썸네일 unit id — top-level cover(10860)가
    아니라 이걸 커버 id로 써야 썸네일이 뜬다."""
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
    assert p.cover_item_id == "78112"  # cache_key 접두어, cover(10860) 아님
    assert p.cover_cache_key == "78112_1762208160"
    assert p.item_count == 843


async def test_person_cover_falls_back_to_cover_field():
    """cache_key가 없으면(접두어 못 뽑음) top-level cover로 폴백."""
    dsm = _StubDsm(
        {
            "list": [
                {
                    "id": 5,
                    "name": "지민",
                    "item_count": 12,
                    "show": True,
                    "cover": 555,
                    "additional": {"thumbnail": {}},
                }
            ]
        }
    )
    persons = await DsmPhotoSource(dsm, _sid()).persons("team")
    assert persons[0].cover_item_id == "555"


async def test_hidden_person_group_skipped():
    dsm = _StubDsm(
        {
            "list": [
                {"id": 1, "name": "", "cover": 100, "show": False, "additional": {}},
            ]
        }
    )
    assert await DsmPhotoSource(dsm, _sid()).persons("personal") == []

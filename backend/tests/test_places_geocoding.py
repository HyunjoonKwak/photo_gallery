"""장소(지오코딩) 그룹 파싱 — 실 NAS(DSM 7.2) raw 응답 기준.

2026-07 실 NAS 확인: Geocoding list는 country/country_id/first_level/
second_level 계층을 준다 → 프론트가 국가→지역(first_level)으로 묶는다.
이 필드들이 PlaceInfo로 그대로 넘어가는지 잠근다."""

import time as _time

from app.photos.dsm_source import DsmPhotoSource


class _StubDsm:
    def __init__(self, data):
        self.data = data

    async def call(self, api, method, **kwargs):
        return self.data


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_places_carry_country_and_first_level():
    dsm = _StubDsm(
        {
            "list": [
                {
                    "id": 44,
                    "name": "Seoul",
                    "item_count": 537,
                    "country": "South Korea",
                    "country_id": 1,
                    "first_level": "Seoul",
                    "second_level": "",
                },
                {
                    "id": 227,
                    "name": "The Rocks, Sydney",
                    "item_count": 94,
                    "country": "Australia",
                    "country_id": 1087,
                    "first_level": "Sydney",
                    "second_level": "The Rocks",
                },
            ]
        }
    )
    places = await DsmPhotoSource(dsm, _sid()).places("team")
    by_id = {p.id: p for p in places}

    seoul = by_id["44"]
    assert seoul.country == "South Korea"
    assert seoul.country_id == 1
    assert seoul.first_level == "Seoul"
    assert seoul.second_level is None  # 빈 문자열 → None

    rocks = by_id["227"]
    assert rocks.country == "Australia"
    assert rocks.first_level == "Sydney"
    assert rocks.second_level == "The Rocks"

"""미리보기 카드(도시/폴더)용 limit — 그룹 전체를 페이징하지 않고 한 페이지만
받아 앨범/폴더 뷰 로딩 부하를 줄인다(성능 개선)."""

import json
import time as _time

from app.photos.dsm_source import DsmPhotoSource


class _CountingDsm:
    """호출 횟수를 세고, 요청 limit만큼 더미 아이템을 돌려주는 스텁."""

    def __init__(self):
        self.calls: list[dict] = []

    TOTAL = 1000  # 그룹에 존재하는 전체 아이템 수(페이징 종료용)

    async def call(self, api, method, **kwargs):
        extra = kwargs.get("extra", {}) or {}
        self.calls.append(extra)
        if "Browse.Item" in api and method == "list":
            n = int(extra.get("limit", 0))
            base = int(extra.get("offset", 0))
            count = max(0, min(n, self.TOTAL - base))
            return {
                "list": [
                    {"id": base + i, "filename": f"f{base + i}.jpg", "time": 1_700_000_000}
                    for i in range(count)
                ]
            }
        return {"list": []}


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_place_items_limit_single_page_and_capped():
    dsm = _CountingDsm()
    src = DsmPhotoSource(dsm, _sid())
    items = await src.place_items("team", "44", limit=4)

    # 정확히 4장으로 캡.
    assert len(items) == 4
    # Browse.Item list 호출은 딱 한 번(전량 페이징 안 함).
    item_calls = [c for c in dsm.calls if "offset" in c and "geocoding_id" in c]
    assert len(item_calls) == 1
    # 필터로 몇 장 빠질 여유분(limit+8)만 요청.
    assert item_calls[0]["limit"] == 12
    assert item_calls[0]["geocoding_id"] == 44


async def test_place_items_no_limit_paginates_fully():
    dsm = _CountingDsm()
    src = DsmPhotoSource(dsm, _sid())
    # limit 없으면 1000씩 페이징: 한 페이지가 1000 미만이면 종료.
    items = await src.place_items("team", "44")
    item_calls = [c for c in dsm.calls if "geocoding_id" in c]
    assert item_calls[0]["limit"] == 1000
    # 스텁이 매 페이지 1000장을 주면 무한이 되므로, 첫 페이지가 1000 → 다음
    # 페이지 offset=1000도 1000... 실제 종료는 len<page_size. 여기선 계약만
    # 확인(첫 호출 limit=1000, 미리보기 아님).
    assert len(items) >= 1000

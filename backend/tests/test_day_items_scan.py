"""Large day listings use bounded parallel continuation pages."""

import asyncio
from datetime import date

from app.photos import dsm_browse
from app.photos.dsm_source import DsmPhotoSource


class _DayDsm:
    TOTAL = 13

    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0
        self.day_calls = 0
        self.sort_directions: list[str] = []

    async def call(self, api, method, **kwargs):
        extra = kwargs.get("extra", {}) or {}
        if "Browse.Item" not in api or "start_time" not in extra:
            return {"list": []}  # trash-folder lookup
        self.day_calls += 1
        self.sort_directions.append(str(extra.get("sort_direction")))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)
            offset = int(extra["offset"])
            limit = int(extra["limit"])
            count = max(0, min(limit, self.TOTAL - offset))
            return {
                "list": [
                    {
                        "id": offset + i,
                        "filename": f"p{offset + i}.jpg",
                        "time": int(extra["start_time"]) + offset + i,
                    }
                    for i in range(count)
                ]
            }
        finally:
            self.active -= 1


async def test_large_day_continuation_pages_are_parallel(monkeypatch):
    # Small pages keep the regression test quick while exercising 3 data pages.
    monkeypatch.setattr(dsm_browse, "_PAGE", 5)
    dsm = _DayDsm()
    source = DsmPhotoSource(dsm, "day-scan-sid")

    items = await source.items("team", date.today().isoformat())

    assert [item.id for item in items] == [str(i) for i in reversed(range(dsm.TOTAL))]
    assert set(dsm.sort_directions) == {"desc"}
    assert dsm.day_calls == 1 + dsm_browse._DAY_PAGE_CONCURRENCY
    assert dsm.max_active == dsm_browse._DAY_PAGE_CONCURRENCY

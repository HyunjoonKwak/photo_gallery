"""비디오 탭 성능 개선 — 라이브러리 전량 스캔을 병렬 물결로 조회하고 결과를
캐시한다(반복 조회 즉시). type==video만 필터, 휴지통/tombstone 제외."""

import time as _time

from app.photos.dsm_source import DsmPhotoSource, invalidate_bucket_cache


class _CountingDsm:
    TOTAL = 12000  # 라이브러리 전체 아이템 수 (매 10번째가 video)

    def __init__(self):
        self.list_calls = 0

    async def call(self, api, method, **kwargs):
        extra = kwargs.get("extra", {}) or {}
        if "Browse.Item" in api and method == "list":
            self.list_calls += 1
            base = int(extra.get("offset", 0))
            n = int(extra.get("limit", 0))
            count = max(0, min(n, self.TOTAL - base))
            return {
                "list": [
                    {
                        "id": base + i,
                        "filename": f"f{base + i}",
                        "time": 1_700_000_000,
                        "type": "video" if (base + i) % 10 == 0 else "photo",
                        "additional": {"thumbnail": {"cache_key": f"{base + i}_1"}},
                    }
                    for i in range(count)
                ]
            }
        return {"list": []}  # Browse.Folder (trash lookup) → no #trash


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_videos_filters_and_caches():
    dsm = _CountingDsm()
    sid = _sid()
    src = DsmPhotoSource(dsm, sid)

    vids = await src.videos("team")
    # 12000개 중 매 10번째 = 1200개 video.
    assert len(vids) == 1200
    assert all(v.type == "video" for v in vids)
    calls_after_first = dsm.list_calls
    assert calls_after_first > 0

    # 두 번째 호출은 캐시 → 추가 list 호출 없음.
    vids2 = await src.videos("team")
    assert len(vids2) == 1200
    assert dsm.list_calls == calls_after_first

    # 쓰기 무효화 후엔 다시 스캔.
    invalidate_bucket_cache(sid)
    await src.videos("team")
    assert dsm.list_calls > calls_after_first


async def test_videos_scan_is_parallel_waves():
    """12000 아이템 / 5000 페이지 = 3 페이지. 동시성(_SCAN_CONCURRENCY)이면 한
    물결에 다 담겨 그 개수만큼 offset을 조회한다(짧은 페이지로 한 물결 종료)."""
    from app.photos.dsm_source import _SCAN_CONCURRENCY

    dsm = _CountingDsm()
    src = DsmPhotoSource(dsm, _sid())
    await src.videos("team")
    # 한 물결만에 끝 — offset 0/5000/10000은 내용, 나머지는 빈 페이지.
    assert dsm.list_calls == _SCAN_CONCURRENCY

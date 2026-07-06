"""인물 이름 지정 + 같은 이름 자동 병합.

이름 지정(set_name)은 실 NAS 확실, 병합 API는 미검증이라 best-effort.
여기선 계약(같은 이름 있으면 병합 경로, 없으면 이름만)과 mock 동작을 잠근다."""

import time as _time

from app.photos.dsm_source import DsmPhotoSource
from app.photos.mock import MockPhotoSource


# --------------------------------------------------------------- mock (UX)
async def test_mock_name_unnamed_person():
    src = MockPhotoSource()
    unnamed = next(p for p in await src.persons("personal") if p.name == "")
    res = await src.name_person("personal", unnamed.id, "아빠")
    assert res["merged_into"] is None
    after = await src.persons("personal")
    assert any(p.id == unnamed.id and p.name == "아빠" for p in after)


async def test_mock_name_merges_into_existing():
    src = MockPhotoSource()
    persons = await src.persons("personal")
    unnamed = next(p for p in persons if p.name == "")
    target = next(p for p in persons if p.name == "엄마")
    before = target.item_count or 0

    res = await src.name_person("personal", unnamed.id, "엄마")
    assert res["merged_into"] == target.id

    after = await src.persons("personal")
    assert unnamed.id not in [p.id for p in after]  # 병합돼 사라짐
    merged = next(p for p in after if p.id == target.id)
    assert (merged.item_count or 0) >= before  # 멤버가 합쳐짐
    # person_items도 병합 소스 사진을 포함.
    assert len(await src.person_items("personal", target.id)) == merged.item_count


# --------------------------------------------------------------- DSM (계약)
class _NameStub:
    def __init__(self, persons_list):
        self.persons_list = persons_list
        self.calls = []

    async def call(self, api, method, **kwargs):
        self.calls.append((api, method, kwargs.get("extra", {}) or {}))
        if "Browse.Person" in api and method == "list":
            return {"list": self.persons_list}
        return {"success": True}


def _person(pid, name):
    return {
        "id": pid,
        "name": name,
        "item_count": 10,
        "show": True,
        "cover": pid * 100,
        "additional": {"thumbnail": {"cache_key": f"{pid}_1"}},
    }


def _sid() -> str:
    return f"sid-{_time.monotonic_ns()}"


async def test_dsm_name_person_sets_name_only_when_unique():
    dsm = _NameStub([_person(1, "엄마")])
    await DsmPhotoSource(dsm, _sid()).name_person("personal", "2", "아빠")
    methods = [(m, e) for (a, m, e) in dsm.calls if "Browse.Person" in a]
    # 실 NAS 확인: 이름 지정 메서드는 `set`(set_name 아님).
    set_calls = [e for (m, e) in methods if m == "set"]
    merge_calls = [e for (m, e) in methods if m == "merge"]
    assert set_calls and set_calls[0]["id"] == 2 and set_calls[0]["name"] == "아빠"
    assert not merge_calls  # 같은 이름 없음 → 병합 안 함


async def test_dsm_name_person_merges_into_existing_name():
    dsm = _NameStub([_person(1, "엄마")])
    res = await DsmPhotoSource(dsm, _sid()).name_person("personal", "2", "엄마")
    methods = [(m, e) for (a, m, e) in dsm.calls if "Browse.Person" in a]
    assert any(m == "set" for (m, e) in methods)  # 이름 먼저 지정
    merge = [e for (m, e) in methods if m == "merge"]
    assert merge and merge[0]["target"] == 1  # 병합 대상
    assert res["merged_into"] == "1"

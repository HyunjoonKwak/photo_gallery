"""이벤트 클러스터링 단위테스트 (정리 마법사 Phase 2)."""

from app.organize.events import cluster_events, name_hint
from datetime import datetime


def _rows(*ts):
    return [(f"id{i}", t) for i, t in enumerate(ts)]


def test_gap_splits_clusters():
    rows = _rows(
        "2024-05-05T10:00:00", "2024-05-05T11:00:00", "2024-05-05T12:00:00",
        "2024-05-06T09:00:00", "2024-05-06T09:30:00", "2024-05-06T10:00:00",
    )
    out = cluster_events(rows, gap_hours=4, min_photos=3)
    assert len(out) == 2
    assert out[0]["count"] == 3 and out[0]["start"].startswith("2024-05-06")


def test_min_photos_filters_small():
    rows = _rows("2024-01-01T10:00:00", "2024-01-01T10:05:00")
    assert cluster_events(rows, gap_hours=4, min_photos=3) == []


def test_missing_taken_at_skipped():
    rows = [("a", ""), ("b", None), ("c", "2024-01-01T10:00:00")]  # type: ignore[list-item]
    out = cluster_events(rows, gap_hours=4, min_photos=1)
    assert len(out) == 1 and out[0]["item_ids"] == ["c"]


def test_midnight_crossing_stays_one_cluster():
    rows = _rows("2024-03-01T23:00:00", "2024-03-02T01:00:00")
    out = cluster_events(rows, gap_hours=4, min_photos=2)
    assert len(out) == 1
    assert out[0]["name_hint"] == "2024-03-01~02"


def test_name_hint_formats():
    d = datetime.fromisoformat
    assert name_hint(d("2024-05-05T10:00"), d("2024-05-05T22:00")) == "2024-05-05"
    assert name_hint(d("2024-05-05T10:00"), d("2024-05-07T22:00")) == "2024-05-05~07"
    assert name_hint(d("2024-05-30T10:00"), d("2024-06-02T22:00")) == "2024-05-30~06-02"


def test_annotate_copied_hides_mostly_copied():
    from app.organize.events import annotate_copied

    events = [
        {"count": 10, "item_ids": [str(i) for i in range(10)]},
        {"count": 10, "item_ids": [str(i) for i in range(100, 110)]},
    ]
    copied = {str(i) for i in range(9)}  # 첫 이벤트 90% 복사됨
    kept, hidden = annotate_copied(events, copied)
    assert hidden == 1
    assert len(kept) == 1 and kept[0]["copied_count"] == 0


def test_annotate_copied_partial_kept():
    from app.organize.events import annotate_copied

    events = [{"count": 10, "item_ids": [str(i) for i in range(10)]}]
    kept, hidden = annotate_copied(events, {"0", "1", "2"})
    assert hidden == 0 and kept[0]["copied_count"] == 3

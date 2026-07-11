"""이벤트 클러스터링 — 정리 마법사 Phase 2 (ORGANIZE_WIZARD.md).

photo_cache(personal)의 taken_at을 시간순으로 훑어, 연속 사진 간격이
gap_hours를 넘으면 새 이벤트로 나눈다. min_photos 미만 클러스터는 버린다.
v1 name_hint는 날짜 범위만(장소 라벨은 지오코딩 역매핑 프로브 후 — 미결 2번).
"""

from __future__ import annotations

from datetime import datetime

from ..db import connect


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def name_hint(start: datetime, end: datetime) -> str:
    """"YYYY-MM-DD" / 같은 달 "YYYY-MM-DD~DD" / 그 외 "YYYY-MM-DD~MM-DD"."""
    s = start.date()
    e = end.date()
    if s == e:
        return s.isoformat()
    if (s.year, s.month) == (e.year, e.month):
        return f"{s.isoformat()}~{e.day:02d}"
    return f"{s.isoformat()}~{e.month:02d}-{e.day:02d}"


def cluster_events(
    rows: list[tuple[str, str]],  # (file_id, taken_at iso)
    gap_hours: float = 4.0,
    min_photos: int = 8,
) -> list[dict]:
    """taken_at 정렬 → 갭 분리 → 최소 장수 필터. 결측 taken_at은 제외."""
    dated = []
    for fid, ts in rows:
        dt = _parse(ts)
        if dt is not None:
            dated.append((dt, fid))
    dated.sort(key=lambda x: x[0])
    if not dated:
        return []
    gap = gap_hours * 3600.0
    clusters: list[list[tuple[datetime, str]]] = [[dated[0]]]
    for prev, cur in zip(dated, dated[1:]):
        if (cur[0] - prev[0]).total_seconds() > gap:
            clusters.append([])
        clusters[-1].append(cur)
    out = []
    for c in clusters:
        if len(c) < min_photos:
            continue
        start, end = c[0][0], c[-1][0]
        out.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "count": len(c),
                "item_ids": [fid for _, fid in c],
                "name_hint": name_hint(start, end),
            }
        )
    out.sort(key=lambda e: e["start"], reverse=True)  # 최신 이벤트 먼저
    return out


def event_rows(sqlite_path: str, space: str = "personal") -> list[tuple[str, str]]:
    with connect(sqlite_path) as conn:
        return [
            (r["file_id"], r["taken_at"])
            for r in conn.execute(
                "SELECT file_id, taken_at FROM photo_cache WHERE space = ?",
                (space,),
            )
        ]


def annotate_copied(
    events: list[dict], copied: set[str], hide_threshold: float = 0.9
) -> tuple[list[dict], int]:
    """각 이벤트에 copied_count를 달고, 대부분(기본 90%↑) 복사된 이벤트는
    숨긴다. (hidden 수를 함께 반환 — UI 안내용)"""
    kept: list[dict] = []
    hidden = 0
    for e in events:
        n = sum(1 for i in e["item_ids"] if i in copied)
        e["copied_count"] = n
        if e["count"] > 0 and n / e["count"] >= hide_threshold:
            hidden += 1
            continue
        kept.append(e)
    return kept, hidden

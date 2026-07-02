"""Phase-2 duplicate detection: scan job + grouping (docs/IMPROVEMENTS.md D절).

Scan: iterates the space's day buckets, computes (sha256, phash) per item via
the PhotoSource, and persists them into ``photo_cache``. The job row in SQLite
tracks progress; because hashes persist per item, an interrupted scan resumes
for free — already-hashed items are skipped.

Grouping: exact duplicates share a sha256. Near-duplicates are found with the
multi-index trick (8 bands × 8 bits: any pair with Hamming distance ≤ 7 shares
at least one identical band by pigeonhole), then union-find over candidate
pairs with distance ≤ threshold — no O(n²) full pairwise pass (dupeGuru
반면교사). Reference selection: highest resolution → largest file → earliest
taken_at; the user can override per group in the UI.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from .db import connect
from .photos.source import PhotoSource
from .schemas import DedupGroup, DedupItem, DedupJob

logger = logging.getLogger(__name__)

JOB_TYPE = "dedup_scan"
_HASH_CONCURRENCY = 8  # parallel thumbnail downloads per scan
_CHUNK = 100  # items hashed + persisted + progress-updated per batch
_BANDS = 8  # 8 bands × 8 bits — guarantees recall for hamming ≤ 7 ≥ threshold(≤10 UI cap? threshold ≤ 7 보장)

# In-process handles to running scan tasks, keyed by space.
_running_tasks: dict[str, asyncio.Task[None]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------ job rows


def _job_row_to_model(row) -> DedupJob:
    return DedupJob(
        id=row["id"],
        space=row["space"],
        status=row["status"],
        processed=row["processed"],
        total=row["total"],
        error=row["error"],
        updated_at=row["updated_at"],
    )


def latest_job(sqlite_path: str, space: str) -> DedupJob | None:
    with connect(sqlite_path) as conn:
        row = conn.execute(
            "SELECT * FROM job WHERE type = ? AND space = ? ORDER BY id DESC LIMIT 1",
            (JOB_TYPE, space),
        ).fetchone()
    return _job_row_to_model(row) if row else None


def _create_job(sqlite_path: str, space: str) -> int:
    with connect(sqlite_path) as conn:
        cur = conn.execute(
            "INSERT INTO job (type, space, status, processed, total, created_at, updated_at) "
            "VALUES (?, ?, 'running', 0, 0, ?, ?)",
            (JOB_TYPE, space, _now(), _now()),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def _update_job(sqlite_path: str, job_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with connect(sqlite_path) as conn:
        conn.execute(
            f"UPDATE job SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608 - keys are code-controlled
            (*fields.values(), _now(), job_id),
        )
        conn.commit()


def _job_status(sqlite_path: str, job_id: int) -> str:
    with connect(sqlite_path) as conn:
        row = conn.execute("SELECT status FROM job WHERE id = ?", (job_id,)).fetchone()
    return row["status"] if row else "cancelled"


def cancel_scan(sqlite_path: str, space: str) -> bool:
    job = latest_job(sqlite_path, space)
    if not job or job.status != "running":
        return False
    _update_job(sqlite_path, job.id, status="cancelled")
    return True


# ------------------------------------------------------------------ scanning


async def _run_scan(source: PhotoSource, sqlite_path: str, space: str, job_id: int) -> None:
    try:
        buckets = await source.buckets(space)
        total = sum(b.count for b in buckets)
        _update_job(sqlite_path, job_id, total=total)

        with connect(sqlite_path) as conn:
            cached = {
                row["file_id"]
                for row in conn.execute(
                    "SELECT file_id FROM photo_cache "
                    "WHERE space = ? AND sha256 IS NOT NULL AND phash IS NOT NULL",
                    (space,),
                )
            }

        processed = 0
        since_write = 0
        skipped = 0
        sem = asyncio.Semaphore(_HASH_CONCURRENCY)

        async def hash_one(item):
            # A single unhashable photo (broken thumbnail, transient 5xx) must
            # not fail the whole scan — skip it and keep going.
            async with sem:
                try:
                    sha, ph = await source.item_hashes(space, item)
                except Exception:  # noqa: BLE001 - per-item boundary
                    return None
            return (
                item.id, space, item.filename, item.taken_at, item.cache_key,
                item.width, item.height, item.size, sha, ph,
            )

        for bucket in buckets:
            if _job_status(sqlite_path, job_id) == "cancelled":
                return
            items = await source.items(space, bucket.day)
            to_hash = [it for it in items if it.id not in cached]
            processed += len(items) - len(to_hash)  # already-hashed count now
            # Process in chunks so a huge day (thousands of photos) still shows
            # progress and persists incrementally (resume-friendly).
            for start in range(0, len(to_hash), _CHUNK):
                if _job_status(sqlite_path, job_id) == "cancelled":
                    return
                chunk = to_hash[start : start + _CHUNK]
                results = await asyncio.gather(*(hash_one(it) for it in chunk))
                rows = [r for r in results if r is not None]
                skipped += len(chunk) - len(rows)
                processed += len(chunk)
                if rows:
                    with connect(sqlite_path) as conn:
                        conn.executemany(
                            "INSERT OR REPLACE INTO photo_cache "
                            "(file_id, space, path, taken_at, thumb_key, width, "
                            " height, size, sha256, phash) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            rows,
                        )
                        conn.commit()
                _update_job(sqlite_path, job_id, processed=processed)

        if skipped:
            logger.warning("dedup scan skipped %d unhashable photos", skipped)
        _update_job(sqlite_path, job_id, processed=processed, status="done")
    except Exception as exc:  # noqa: BLE001 - job boundary: persist, don't crash the app
        logger.exception("dedup scan failed (space=%s)", space)
        _update_job(sqlite_path, job_id, status="failed", error=str(exc))
    finally:
        _running_tasks.pop(space, None)


async def start_scan(
    source: PhotoSource, sqlite_path: str, space: str, *, sync: bool = False
) -> DedupJob:
    """Start (or run synchronously) a scan for the space. One at a time."""
    current = latest_job(sqlite_path, space)
    if current and current.status == "running":
        return current
    job_id = _create_job(sqlite_path, space)
    if sync:
        await _run_scan(source, sqlite_path, space, job_id)
    else:
        _running_tasks[space] = asyncio.create_task(
            _run_scan(source, sqlite_path, space, job_id)
        )
    job = latest_job(sqlite_path, space)
    assert job is not None
    return job


# ------------------------------------------------------------------ grouping


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _pick_reference(items: list[DedupItem]) -> str:
    """해상도 → 용량 → 촬영일 오름차순(원본 우선 근사) 순으로 보관본 선택."""
    best = max(
        items,
        key=lambda i: (
            (i.width or 0) * (i.height or 0),
            i.size or 0,
            # earlier taken_at wins on ties → negate by sorting trick below
        ),
    )
    tied = [
        i
        for i in items
        if ((i.width or 0) * (i.height or 0), i.size or 0)
        == ((best.width or 0) * (best.height or 0), best.size or 0)
    ]
    return min(tied, key=lambda i: i.taken_at).id


def _make_group(kind: str, group_id: str, items: list[DedupItem]) -> DedupGroup:
    reference_id = _pick_reference(items)
    wasted = sum(i.size or 0 for i in items if i.id != reference_id)
    return DedupGroup(
        id=group_id,
        kind=kind,
        items=sorted(items, key=lambda i: (i.id != reference_id, i.taken_at)),
        reference_id=reference_id,
        wasted_bytes=wasted,
    )


def build_groups(sqlite_path: str, space: str, threshold: int) -> list[DedupGroup]:
    with connect(sqlite_path) as conn:
        rows = conn.execute(
            "SELECT file_id, space, path, taken_at, thumb_key, width, height, size, "
            "       sha256, phash FROM photo_cache "
            "WHERE space = ? AND sha256 IS NOT NULL AND phash IS NOT NULL",
            (space,),
        ).fetchall()

    items: list[DedupItem] = []
    phashes: list[int] = []
    shas: list[str] = []
    for row in rows:
        items.append(
            DedupItem(
                id=row["file_id"],
                filename=row["path"] or "",
                taken_at=row["taken_at"] or "",
                width=row["width"] or 0,
                height=row["height"] or 0,
                size=row["size"],
                cache_key=row["thumb_key"] or "",
                placeholder_color=None,
                folder=None,
                space=row["space"],
            )
        )
        phashes.append(int(row["phash"], 16))
        shas.append(row["sha256"])

    groups: list[DedupGroup] = []

    # 1) Exact duplicates: identical sha256.
    by_sha: dict[str, list[int]] = {}
    for i, sha in enumerate(shas):
        by_sha.setdefault(sha, []).append(i)
    in_exact: set[int] = set()
    for sha, idxs in by_sha.items():
        if len(idxs) > 1:
            in_exact.update(idxs)
            groups.append(_make_group("exact", f"e-{sha[:12]}", [items[i] for i in idxs]))

    # 2) Near duplicates among the rest: banded candidate buckets + union-find.
    rest = [i for i in range(len(items)) if i not in in_exact]
    uf = _UnionFind(len(items))
    buckets: dict[tuple[int, int], list[int]] = {}
    for i in rest:
        ph = phashes[i]
        for band in range(_BANDS):
            buckets.setdefault((band, (ph >> (8 * band)) & 0xFF), []).append(i)
    for candidates in buckets.values():
        if len(candidates) < 2:
            continue
        for a_pos in range(len(candidates)):
            for b_pos in range(a_pos + 1, len(candidates)):
                a, b = candidates[a_pos], candidates[b_pos]
                if (phashes[a] ^ phashes[b]).bit_count() <= threshold:
                    uf.union(a, b)

    clusters: dict[int, list[int]] = {}
    for i in rest:
        clusters.setdefault(uf.find(i), []).append(i)
    for members in clusters.values():
        if len(members) > 1:
            members.sort()
            groups.append(
                _make_group("similar", f"s-{items[members[0]].id}", [items[i] for i in members])
            )

    groups.sort(key=lambda g: g.wasted_bytes, reverse=True)
    return groups


def remove_cached_items(sqlite_path: str, item_ids: list[str]) -> None:
    """Drop cache rows for items removed from the library (delete/copy-undo)."""
    if not item_ids:
        return
    with connect(sqlite_path) as conn:
        conn.executemany(
            "DELETE FROM photo_cache WHERE file_id = ?", [(i,) for i in item_ids]
        )
        conn.commit()

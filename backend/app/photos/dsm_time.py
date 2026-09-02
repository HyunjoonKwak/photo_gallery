"""Convert Synology Photos' floating wall-clock timestamps.

Foto/FotoTeam encode a timezone-less capture time in an epoch-shaped integer:
``2020-02-25 12:20:49`` is returned as the Unix value for
``2020-02-25 12:20:49 UTC`` regardless of the NAS timezone. Treating that
integer as a real instant and calling local ``fromtimestamp`` adds KST again.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def decode_wall_clock(epoch: int | float) -> datetime:
    """Decode a DSM Foto ``time`` value without applying the host timezone."""
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def date_from_epoch(epoch: int | float) -> date:
    return decode_wall_clock(epoch).date()


def encode_wall_clock(value: datetime) -> int:
    """Encode a timezone-less user/EXIF wall-clock for DSM Foto APIs."""
    if value.tzinfo is not None:
        raise ValueError("DSM wall-clock은 timezone 없는 datetime이어야 합니다")
    return int(value.replace(tzinfo=timezone.utc).timestamp())


def day_range(day: date) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day)
    return encode_wall_clock(start), encode_wall_clock(start + timedelta(days=1))

"""Derive a photo's real capture date from EXIF or, failing that, its filename.

Many library photos (KakaoTalk / app exports) carry no EXIF capture date, so
both this app and Synology fall back to the file's mtime — which move/copy
corrupts (dates collapse to the copy time). The true capture time usually
survives in the filename: a 13-digit ms epoch, a YYYYMMDD run, Screenshot_… etc.
This module extracts it so we can bake it back into the file (EXIF + mtime).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

# Accept only plausible capture dates — rejects random digit runs that happen to
# parse (e.g. an unrelated 8-digit id). 1990 predates digital photos we'd see;
# 2100 is a safe upper bound that still catches a bogus far-future epoch.
_MIN_YEAR = 1990
_MAX_YEAR = 2100


def _valid(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if _MIN_YEAR <= dt.year <= _MAX_YEAR else None


def _from_parts(y, mo, d, h=0, mi=0, s=0) -> datetime | None:
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except ValueError:
        return None


def _from_epoch(value: int, *, millis: bool) -> datetime | None:
    # Floor to whole seconds (drop sub-second) — capture times don't need ms.
    try:
        return datetime.fromtimestamp(value // 1000 if millis else value)
    except (ValueError, OSError, OverflowError):
        return None


# Ordered handlers — first valid match wins. Longer/more specific patterns first.
_YMD = r"(19|20)\d{2}"


def parse_from_filename(name: str) -> datetime | None:
    """Best-effort capture datetime from a filename; None if no confident match."""
    s = name

    # 1) YYYYMMDDHHMMSS (14 digits, e.g. IMG_20170221143022) — must start 19/20.
    m = re.search(r"(?<!\d)((?:19|20)\d{2})([01]\d)([0-3]\d)([0-2]\d)([0-5]\d)([0-5]\d)(?!\d)", s)
    if m:
        dt = _valid(_from_parts(*m.groups()))
        if dt:
            return dt

    # 2) 13-digit millisecond epoch, optionally followed by a short sequence
    #    suffix (e.g. 1487654687945.jpg, or KakaoTalk's 1502088228879113.jpg =
    #    13-digit ms + 3-digit seq). Take the first 13 digits as the epoch.
    m = re.search(r"(?<!\d)(\d{13})\d{0,6}(?!\d)", s)
    if m:
        dt = _valid(_from_epoch(int(m.group(1)), millis=True))
        if dt:
            return dt

    # 3) YYYY[sep]MM[sep]DD with optional [sep]HH[sep]MM[sep]SS
    #    (2016-05-10, 2016_05_10, Screenshot_2016-05-10-19-41-17).
    m = re.search(
        r"(?<!\d)((?:19|20)\d{2})[-_.]?([01]\d)[-_.]?([0-3]\d)"
        r"(?:[-_.\sT]?([0-2]\d)[-_.:]?([0-5]\d)[-_.:]?([0-5]\d))?(?!\d)",
        s,
    )
    if m:
        y, mo, d, h, mi, sec = m.groups()
        dt = _valid(_from_parts(y, mo, d, h or 0, mi or 0, sec or 0))
        if dt:
            return dt

    # 4) 10-digit second epoch (rare here, checked after date strings so an
    #    8-digit date isn't misread — the lookarounds keep it a standalone run).
    m = re.search(r"(?<!\d)(\d{10})(?!\d)", s)
    if m:
        dt = _valid(_from_epoch(int(m.group(1)), millis=False))
        if dt:
            return dt

    return None


# EXIF tags: DateTimeOriginal, DateTimeDigitized, DateTime.
_EXIF_DATE_TAGS = (36867, 36868, 306)


def read_exif_datetime(disk_path: str) -> datetime | None:
    """EXIF capture datetime via Pillow, or None (no EXIF / unreadable)."""
    try:
        from PIL import Image

        with Image.open(disk_path) as img:
            exif = img.getexif()
            # DateTimeOriginal lives in the Exif IFD (0x8769), not the base IFD.
            merged = dict(exif)
            try:
                merged.update(exif.get_ifd(0x8769))
            except Exception:  # noqa: BLE001 - some files have no Exif IFD
                pass
    except Exception:  # noqa: BLE001 - not an image / truncated / no exif
        return None
    for tag in _EXIF_DATE_TAGS:
        raw = merged.get(tag)
        if not raw:
            continue
        try:
            naive = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
        # 이 라이브러리(삼성/한국폰) EXIF DateTime은 UTC로 저장돼 있고 Synology도
        # 시스템 TZ를 더해 로컬로 표시한다(실 NAS 확인: 파일명 로컬시각 == DTO+9h).
        # 그래서 UTC로 간주해 컨테이너 로컬(TZ=Asia/Seoul)로 변환해야 파일명·
        # Synology와 일치한다(안 하면 9시간·자정 근처 하루 어긋남).
        local = naive.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return _valid(local)
    return None


def resolve(disk_path: str, name: str) -> tuple[datetime | None, str]:
    """(capture_datetime, source) where source is exif | filename | none.

    EXIF is authoritative — a file that already has a valid EXIF date is correct
    and must not be overwritten. Otherwise fall back to the filename.
    """
    dt = read_exif_datetime(disk_path)
    if dt:
        return dt, "exif"
    dt = parse_from_filename(name)
    if dt:
        return dt, "filename"
    return None, "none"

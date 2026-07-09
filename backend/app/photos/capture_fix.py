"""Bake a corrected capture date into photo files on the (writable) homes mount.

Scope: files under the owner's home (`/homes/<user>/…`) — the container runs as
that owner (uid 1026), so with the mount opened read-write it can edit them.
For JPEGs we write the EXIF capture date (survives moves, read first by Synology);
for every file we also set the filesystem mtime (Synology's fallback). This is a
deliberate exception to "file ops via DSM API only" — DSM has no EXIF/mtime API.
"""

from __future__ import annotations

import os
from datetime import datetime

from . import capture_date

_MOUNT = os.environ.get("THUMB_MOUNT_HOMES", "").rstrip("/")
_MOUNT_TEAM = os.environ.get("THUMB_MOUNT_TEAM", "").rstrip("/")
_MEDIA_EXT = (
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".bmp", ".webp",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv",
)
_JPEG_EXT = (".jpg", ".jpeg")


def disk_path(fs_id: str) -> str | None:
    """`/homes/<user>/…` or `/photo/…`(team) → mount path, else None."""
    if _MOUNT and fs_id.startswith("/homes/"):
        return os.path.join(_MOUNT, fs_id[len("/homes/") :])
    if _MOUNT_TEAM and fs_id.startswith("/photo/"):
        return os.path.join(_MOUNT_TEAM, fs_id[len("/photo/") :])
    return None


def _fs_id(disk: str) -> str:
    return "/homes/" + os.path.relpath(disk, _MOUNT)


_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".bmp", ".webp")


def scan_audit(root_fs_id: str, limit: int | None = None) -> list[dict]:
    """Recursively list media under a home folder with the true capture date.

    Detection: filename first (cheap), then EXIF for images whose filename has no
    date (so EXIF-only photos are still surfaced). `current` is the file mtime —
    what both the app (1차 구역) and Synology (fallback) currently show.
    """
    root = disk_path(root_fs_id)
    if not root or not os.path.isdir(root):
        return []
    out: list[dict] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(("@", "#"))]
        for fn in files:
            low = fn.lower()
            if not low.endswith(_MEDIA_EXT):
                continue
            p = os.path.join(dirpath, fn)
            try:
                mtime = os.stat(p).st_mtime
            except OSError:
                continue
            detected = capture_date.parse_from_filename(fn)
            source = "filename" if detected else "none"
            if detected is None and low.endswith(_IMAGE_EXT):
                ex = capture_date.read_exif_datetime(p)
                if ex:
                    detected, source = ex, "exif"
            out.append(
                {
                    "path": _fs_id(p),
                    "filename": fn,
                    "current": datetime.fromtimestamp(mtime).isoformat(),
                    "detected": detected.isoformat() if detected else None,
                    "source": source,
                }
            )
            if limit and len(out) >= limit:
                return out
    return out


def _write_exif_jpeg(disk: str, dt: datetime) -> None:
    import piexif

    try:
        exif = piexif.load(disk)
    except Exception:  # noqa: BLE001 - no/invalid exif segment → start fresh
        exif = {"0th": {}, "Exif": {}, "1st": {}, "GPS": {}, "Interop": {}}
    stamp = dt.strftime("%Y:%m:%d %H:%M:%S").encode()
    exif.setdefault("Exif", {})[piexif.ExifIFD.DateTimeOriginal] = stamp
    exif["Exif"][piexif.ExifIFD.DateTimeDigitized] = stamp
    exif.setdefault("0th", {})[piexif.ImageIFD.DateTime] = stamp
    piexif.insert(piexif.dump(exif), disk)


def _set_mtime(disk: str, dt: datetime) -> None:
    ts = dt.timestamp()
    os.utime(disk, (ts, ts))


def _apply(disk: str, dt: datetime, *, write_exif: bool) -> None:
    if write_exif and disk.lower().endswith(_JPEG_EXT):
        try:
            _write_exif_jpeg(disk, dt)
        except Exception:  # noqa: BLE001 - EXIF write failed; mtime still set
            pass
    _set_mtime(disk, dt)  # after EXIF write so mtime lands on the date


def apply_one(fs_id: str, dt: datetime) -> tuple[bool, str]:
    """Manual/explicit: write `dt` into the file (EXIF for JPEG + mtime)."""
    disk = disk_path(fs_id)
    if not disk or not os.path.isfile(disk):
        return False, "not-found"
    try:
        _apply(disk, dt, write_exif=True)
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def apply_auto(fs_id: str) -> str:
    """Bring the file's dates in line with its true capture date.

    True date = EXIF (authoritative, if present) else filename. We always set the
    mtime to it — the app (1차 구역) shows mtime and Synology re-reads on change —
    and write EXIF only when it was missing (never overwrite a real EXIF date).
    Files already correct (or with no derivable date) are left untouched.
    """
    disk = disk_path(fs_id)
    if not disk or not os.path.isfile(disk):
        return "not-found"
    exif_dt = capture_date.read_exif_datetime(disk)
    name_dt = capture_date.parse_from_filename(os.path.basename(disk))
    true_dt = exif_dt or name_dt
    if true_dt is None:
        return "no-date"
    try:
        cur = datetime.fromtimestamp(os.stat(disk).st_mtime)
    except OSError:
        return "not-found"
    need_exif = exif_dt is None and name_dt is not None and disk.lower().endswith(_JPEG_EXT)
    need_mtime = abs((cur - true_dt).total_seconds()) >= 86400  # 하루 이상 어긋남
    if not need_exif and not need_mtime:
        return "already-ok"
    try:
        _apply(disk, true_dt, write_exif=need_exif)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"failed:{type(exc).__name__}"

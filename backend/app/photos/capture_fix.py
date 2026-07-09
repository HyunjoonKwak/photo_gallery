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
_MEDIA_EXT = (
    ".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".bmp", ".webp",
    ".mp4", ".mov", ".m4v", ".avi", ".mkv",
)
_JPEG_EXT = (".jpg", ".jpeg")


def disk_path(fs_id: str) -> str | None:
    """`/homes/<user>/…` → mount path, or None if outside the mount."""
    if not (_MOUNT and fs_id.startswith("/homes/")):
        return None
    return os.path.join(_MOUNT, fs_id[len("/homes/") :])


def _fs_id(disk: str) -> str:
    return "/homes/" + os.path.relpath(disk, _MOUNT)


def scan_audit(root_fs_id: str, limit: int | None = None) -> list[dict]:
    """Recursively list media under a home folder with the date we'd apply.

    Filename-only detection (no per-file EXIF open) so a big folder scans fast —
    EXIF is consulted at write time to avoid clobbering already-correct files.
    """
    root = disk_path(root_fs_id)
    if not root or not os.path.isdir(root):
        return []
    out: list[dict] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(("@", "#"))]
        for fn in files:
            if not fn.lower().endswith(_MEDIA_EXT):
                continue
            p = os.path.join(dirpath, fn)
            try:
                mtime = os.stat(p).st_mtime
            except OSError:
                continue
            detected = capture_date.parse_from_filename(fn)
            out.append(
                {
                    "path": _fs_id(p),
                    "filename": fn,
                    "current": datetime.fromtimestamp(mtime).isoformat(),
                    "detected": detected.isoformat() if detected else None,
                    "source": "filename" if detected else "none",
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


def apply_one(fs_id: str, dt: datetime) -> tuple[bool, str]:
    """Write `dt` into the file (EXIF for JPEG, mtime for all). Returns (ok, msg)."""
    disk = disk_path(fs_id)
    if not disk or not os.path.isfile(disk):
        return False, "not-found"
    try:
        if disk.lower().endswith(_JPEG_EXT):
            try:
                _write_exif_jpeg(disk, dt)
            except Exception:  # noqa: BLE001 - EXIF write failed; mtime still set
                pass
        _set_mtime(disk, dt)  # after EXIF write so mtime lands on the date
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


def apply_auto(fs_id: str) -> str:
    """Resolve the date and apply. Skips files that already have a real EXIF date
    (authoritative) or have no detectable date. Returns a status string."""
    disk = disk_path(fs_id)
    if not disk or not os.path.isfile(disk):
        return "not-found"
    dt, source = capture_date.resolve(disk, os.path.basename(disk))
    if source == "exif":
        return "has-exif"  # already correct — don't overwrite
    if source == "none" or dt is None:
        return "no-date"
    ok, msg = apply_one(fs_id, dt)
    return "ok" if ok else f"failed:{msg}"

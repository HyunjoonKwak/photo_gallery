"""Write-side of the DSM photo source (move/delete/undo/folders/trash).

dsm_source.py 분할(2026-07-12) — 사용 규칙은 dsm_browse 모듈 docstring 참고.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time as _time
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Callable

from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..progress import ProgressFn
from ..schemas import (
    AlbumInfo,
    ItemDetail,
    MemberInfo,
    PersonInfo,
    PhotoBucket,
    PhotoFolder,
    PhotoItem,
    PlaceInfo,
    PlacedItem,
)
from .hashing import compute_hashes
from .source import Affected, DeleteOutcome, MoveOutcome

logger = logging.getLogger(__name__)

from .dsm_cache import (
    _BUCKET_CACHE,
    _SID_ACCOUNT,
    _BUCKET_SCANNING,
    _bucket_scope,
    _FOLDER_META,
    _TOP_FOLDER_CACHE,
    _TRASH_TTL,
    _TRASH_LOCK,
    _TRASH_CONCURRENCY,
    _BG_TASKS,
    _bounded_gather,
    _trash_cache_add,
    _trash_cache_remove,
    trash_cache_clear,
    trash_cache_get,
    trash_cache_set,
    _REMOVED_FOLDERS,
    _REMOVED_FOLDER_TTL,
    _REMOVED_ITEMS,
    _BUCKET_TTL,
    _PAGE,
    _VIDEO_CACHE,
    _PERSON_CACHE,
    _PLACE_CACHE,
    _SCAN_CONCURRENCY,
    _tombstoned_folders,
    _tombstoned_items,
    _tombstone_items,
    _untombstone_items,
    invalidate_bucket_cache,
    drop_session_caches,
    invalidate_folder_cache,
    _ns,
)


class _DsmFileOps:
    async def _copymove(
        self,
        src_paths: list[str],
        dest_dir: str,
        *,
        remove_src: bool,
        overwrite: bool = False,
        progress_cb: "Callable[[float], None] | None" = None,
    ) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.CopyMove",
            "start",
            version=3,
            sid=self._sid,
            extra={
                "path": json.dumps(src_paths),
                "dest_folder_path": dest_dir,
                "remove_src": "true" if remove_src else "false",
                "overwrite": "true" if overwrite else "false",
            },
        )
        await self._poll_task(
            "SYNO.FileStation.CopyMove", 3, data.get("taskid"), progress_cb=progress_cb
        )

    async def _rename(self, path: str, new_name: str) -> None:
        # path/name 은 JSON 인코딩 필수(평문이면 error 400 — 실 NAS 확인).
        data = await self._dsm.call(
            "SYNO.FileStation.Rename",
            "rename",
            version=2,
            sid=self._sid,
            extra={"path": json.dumps(path), "name": json.dumps(new_name)},
        )
        # Rename may run as a task (taskid) or return synchronously — poll if async.
        if data.get("taskid"):
            await self._poll_task("SYNO.FileStation.Rename", 2, data.get("taskid"))

    async def _list_entries(self, dir_path: str) -> list[dict]:
        try:
            data = await self._dsm.call(
                "SYNO.FileStation.List",
                "list",
                sid=self._sid,
                extra={
                    "folder_path": dir_path,
                    "limit": 100000,
                    # size for folder-equality comparison (완전 일치 판정).
                    "additional": json.dumps(["size"]),
                },
            )
        except DsmError:
            return []
        return data.get("files", [])

    @staticmethod
    def _entry_size(entry: dict) -> int | None:
        # FileStation.List returns size under additional (or occasionally flat).
        add = entry.get("additional") or {}
        return add.get("size", entry.get("size"))

    async def _folder_extra_count(self, src_dir: str, dest_dir: str) -> int:
        """How many items ``src_dir`` holds that ``dest_dir`` does NOT, compared
        by name+size and recursing into same-named subfolders. 0 ⇒ the source is
        fully contained in the destination (완전 일치). Junk/sidecar entries are
        ignored. Best-effort: a listing error counts as "not contained" so we
        never claim a false full-match."""
        dest = {e.get("name", ""): e for e in await self._list_entries(dest_dir)}
        extra = 0
        for e in await self._list_entries(src_dir):
            name = e.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            d = dest.get(name)
            if e.get("isdir"):
                if d and d.get("isdir"):
                    extra += await self._folder_extra_count(
                        f"{src_dir}/{name}", f"{dest_dir}/{name}"
                    )
                else:
                    extra += 1  # 대상에 없는 하위 폴더 = 추가 항목
            elif not d or d.get("isdir") or self._entry_size(d) != self._entry_size(e):
                extra += 1  # 대상에 없거나 크기가 다른 파일 = 추가 항목
        return extra

    async def _list_filenames(self, dir_path: str) -> set[str]:
        """Filenames directly in a folder (filesystem truth), for conflict checks."""
        return {f.get("name", "") for f in await self._list_entries(dir_path)}

    async def _is_dir_empty(self, dir_path: str) -> bool:
        """True if a folder holds no real content — Synology sidecars(@eaDir)
        and desktop droppings don't count (DSM's own UI treats such folders as
        empty too). Filesystem truth (FileStation), not the lagging Photos
        index."""
        for entry in await self._list_entries(dir_path):
            name = entry.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            return False
        return True

    async def _list_subdir_names(self, dir_path: str) -> set[str]:
        """Sub-folder names directly in a folder, for folder-move conflict checks."""
        return {
            f.get("name", "") for f in await self._list_entries(dir_path) if f.get("isdir")
        }

    @staticmethod
    def _unique_dir_name(taken: set[str], name: str) -> str:
        """folder → folder_1 (or _2, …) not already present (no extension logic)."""
        n = 1
        while f"{name}_{n}" in taken:
            n += 1
        return f"{name}_{n}"

    @staticmethod
    def _unique_name(taken: set[str], filename: str) -> str:
        """photo.jpg → photo_1.jpg (or _2, … ) not present in ``taken``."""
        if "." in filename:
            base, ext = filename.rsplit(".", 1)
            ext = "." + ext
        else:
            base, ext = filename, ""
        n = 1
        while f"{base}_{n}{ext}" in taken:
            n += 1
        return f"{base}_{n}{ext}"

    async def _delete_paths(self, paths: list[str]) -> None:
        data = await self._dsm.call(
            "SYNO.FileStation.Delete",
            "start",
            version=2,
            sid=self._sid,
            extra={"path": json.dumps(paths)},
        )
        await self._poll_task("SYNO.FileStation.Delete", 2, data.get("taskid"))

    async def _poll_task(
        self,
        api: str,
        version: int,
        taskid: str | None,
        *,
        progress_cb: "Callable[[float], None] | None" = None,
    ) -> None:
        """Poll a FileStation task to completion. No hard time cap (대량 폴더
        복사는 60초를 넘김) — 대신 바이트 진행이 5분간 멈추면 실패로 본다.
        progress_cb(0..1)로 진행률을 흘려보낸다(processed_size/total 우선)."""
        if not taskid:
            raise DsmError(100, "파일 작업 태스크를 시작하지 못했습니다.")
        STALL_SECONDS = 300.0  # 5분 무진행 → 중단
        last_change = _time.monotonic()
        last_done = -1
        delay = 0.1  # 적응형: 작은 작업은 ~0.1s에 끝을 감지, 긴 작업은 0.5s로 수렴
        while True:
            status = await self._dsm.call(
                api, "status", version=version, sid=self._sid,
                extra={"taskid": taskid},
            )
            done = status.get("processed_size") or 0
            total = status.get("total") or 0
            if progress_cb:
                if total:
                    progress_cb(max(0.0, min(1.0, done / total)))
                else:
                    pr = status.get("progress")
                    if isinstance(pr, (int, float)) and pr >= 0:
                        progress_cb(max(0.0, min(1.0, float(pr))))
            if status.get("finished"):
                if progress_cb:
                    progress_cb(1.0)
                return
            now = _time.monotonic()
            if done != last_done:
                last_change = now
            last_done = done
            if now - last_change > STALL_SECONDS:
                raise DsmError(100, "파일 작업이 진행되지 않아 중단했습니다(시간 초과).")
            await asyncio.sleep(delay)
            delay = min(delay * 1.6, 0.5)

    async def _item_meta(
        self, space: str, item_ids: list[str]
    ) -> dict[str, dict]:
        """id → {path, folder_id, day} for the given items."""
        data = await self._dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "get",
            version=1,
            sid=self._sid,
            extra={
                "id": json.dumps([int(i) for i in item_ids]),
                "additional": json.dumps(["folder"]),
            },
        )
        prefix = self._share_prefix(space)
        metas = _FOLDER_META.setdefault(self._sid, {})
        out: dict[str, dict] = {}
        for it in data.get("list", []):
            folder = it.get("additional", {}).get("folder") or {}
            folder_name = folder.get("name") if isinstance(folder, dict) else folder
            filename = it.get("filename", "")
            day = date.fromtimestamp(it.get("time", 0)).isoformat()
            fid = str(it.get("folder_id", ""))
            # Remember the source folder's (space, path) so a later 정리 제안 can
            # resolve it by id without the tree having been browsed first — the
            # move originates from the timeline as often as the folder view.
            if fid and folder_name:
                metas.setdefault(fid, (space, folder_name))
            out[str(it.get("id"))] = {
                "path": f"{prefix}{folder_name}/{filename}".replace("//", "/"),
                "filename": filename,
                "folder_id": fid,
                "day": day,
            }
        return out

    def _folder_space(self, folder_id: str) -> str:
        meta = _FOLDER_META.get(self._sid, {}).get(folder_id)
        if meta is None:
            raise DsmError(100, "폴더를 먼저 탐색해야 합니다 (경로 캐시 없음).")
        return meta[0]

    async def _dest_dir(self, dest_folder_id: str) -> tuple[str, str]:
        """dest folder id → (absolute dir path, space).

        `"root:<space>"`(예 root:personal)은 그 공간의 **최상위**를 뜻한다 —
        분할 뷰에서 대상 페인이 루트일 때 1차 폴더를 개인/공용 최상위로 옮기는
        경로. 그 외에는 메타 캐시에서 경로형 id를 해석한다."""
        if dest_folder_id.startswith("root:"):
            space = dest_folder_id.split(":", 1)[1]
            prefix = self._share_prefix(space)
            return prefix.replace("//", "/").rstrip("/") or prefix, space
        meta = _FOLDER_META.get(self._sid, {}).get(dest_folder_id)
        if meta is None:
            raise DsmError(100, "대상 폴더를 먼저 탐색해야 합니다 (경로 캐시 없음).")
        space, name = meta
        prefix = self._share_prefix(space)
        return f"{prefix}{name}".replace("//", "/").rstrip("/") or prefix, space

    # Bulk CopyMove is chunked so count-based progress can be reported between
    # chunks (B-6 진행 바). Partial-failure semantics are unchanged: DSM's own
    # task also processes files one by one server-side.
    # 청크 상한: 개수 200 + URL 인코딩 6KB 예산. CopyMove start는 GET 쿼리라
    # 경로가 길면 DSM nginx 헤더 버퍼(8k)에 걸려 414가 난다(2026-07-03 실측:
    # 146개 장경로 → 22KB → 414). 한글은 인코딩 시 3배가 되므로 바이트로 센다.
    # 기존 25개 고정은 500장 이동 = 20개 순차 태스크(태스크당 폴링 대기 낭비).
    COPYMOVE_CHUNK = 200
    COPYMOVE_URL_BUDGET = 6000

    @classmethod
    def _pack_copymove_chunks(cls, src_paths: list[str]) -> list[list[str]]:
        from urllib.parse import quote

        chunks: list[list[str]] = []
        cur: list[str] = []
        size = 0
        for p in src_paths:
            enc = len(quote(p)) + 6  # 콤마·따옴표 등 JSON/URL 오버헤드
            if cur and (
                len(cur) >= cls.COPYMOVE_CHUNK
                or size + enc > cls.COPYMOVE_URL_BUDGET
            ):
                chunks.append(cur)
                cur, size = [], 0
            cur.append(p)
            size += enc
        if cur:
            chunks.append(cur)
        return chunks

    async def _copymove_chunked(
        self,
        src_paths: list[str],
        dest_dir: str,
        *,
        remove_src: bool,
        on_progress: ProgressFn | None,
        overwrite: bool = False,
        on_task_progress: "Callable[[float], None] | None" = None,
    ) -> None:
        total = len(src_paths)
        if on_progress:
            on_progress(0, total)
        # on_task_progress(0..1): 폴더 복사처럼 항목당 CopyMove 태스크가 오래 걸릴
        # 때 바이트 진행률을 전체 0..1로 환산(청크 인덱스 + 청크 내 진행)한다.
        packed = self._pack_copymove_chunks(src_paths)
        n_chunks = max(1, len(packed))
        start = 0
        for ci, chunk in enumerate(packed):
            cb: Callable[[float], None] | None = None
            if on_task_progress:
                def cb(frac: float, ci=ci) -> None:
                    on_task_progress(min(1.0, (ci + frac) / n_chunks))
            await self._copymove(
                chunk,
                dest_dir,
                remove_src=remove_src,
                overwrite=overwrite,
                progress_cb=cb,
            )
            start += len(chunk)
            if on_progress:
                on_progress(min(start, total), total)
        if on_task_progress:
            on_task_progress(1.0)

    async def conflicts(
        self, space: str, item_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str]]:
        metas = await self._item_meta(space, item_ids)
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        existing = await self._list_filenames(dest_dir)
        return [
            (i, metas[i]["filename"])
            for i in item_ids
            if i in metas and metas[i]["filename"] in existing
        ]

    async def move(
        self,
        space: str,
        item_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
        conflict_strategy: str = "skip",
    ) -> MoveOutcome:
        metas = await self._item_meta(space, item_ids)
        dest_dir, dest_space = await self._dest_dir(dest_folder_id)
        dest_name = (
            "최상위"
            if dest_folder_id.startswith("root:")
            else _FOLDER_META.get(self._sid, {}).get(dest_folder_id, (dest_space, ""))[1]
        )
        outcome = MoveOutcome(dest_space=dest_space, dest_name=dest_name)
        affected: set[tuple[str, str]] = set()

        existing = await self._list_filenames(dest_dir)
        present = [i for i in item_ids if i in metas]
        clashing = [i for i in present if metas[i]["filename"] in existing]
        clash_ids = set(clashing)

        # Items that move under their own name: non-clashing always, plus the
        # clashing ones when overwriting (they replace the existing file).
        if conflict_strategy == "overwrite":
            plain = present
        else:  # skip or rename → clashing items are handled separately/omitted
            plain = [i for i in present if i not in clash_ids]

        if plain:
            await self._copymove_chunked(
                [metas[i]["path"] for i in plain],
                dest_dir,
                remove_src=not copy,
                overwrite=(conflict_strategy == "overwrite"),
                on_progress=on_progress,
            )
        for item_id in plain:
            self._record_placed(outcome, affected, space, dest_space, dest_dir,
                                 metas[item_id], item_id, copy, metas[item_id]["filename"])

        # rename: give each clashing file a fresh "name_1.ext" and place it via a
        # temp folder (CopyMove can't rename its target, so copy→rename→move).
        if conflict_strategy == "rename" and clashing:
            taken = set(existing)
            for item_id in clashing:
                m = metas[item_id]
                new_name = self._unique_name(taken, m["filename"])
                taken.add(new_name)
                await self._place_renamed(m["path"], dest_dir, m["filename"],
                                          new_name, copy=copy)
                self._record_placed(outcome, affected, space, dest_space, dest_dir,
                                    m, item_id, copy, new_name)

        if not copy and outcome.moved:
            # Hide moved ids at their OLD location right away — Photos keeps them
            # under the old folder_id until it reindexes (실 NAS: "이동했는데
            # 원본 폴더에 그대로 보임"). The item reappears at the destination
            # with a new id once reindexed (프론트 resettle 재조회).
            _tombstone_items(self._sid, [p.id for p in outcome.moved])
            # A move can leave the source folder(s) empty — surface them so the
            # client can offer 정리(빈 폴더 삭제).
            outcome.emptied = await self._detect_emptied(space, metas, outcome.moved)

        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

    async def _detect_emptied(
        self, space: str, metas: dict[str, dict], moved: list[PlacedItem]
    ) -> list[tuple[str, str, str]]:
        """Source folders left empty after moving ``moved`` out of them.

        Grouped by source folder id; each is re-listed once (post-move) against
        the filesystem. Returns (folder_id, basename, space) for the empty ones.
        """
        # folder_id → (dir_path, basename); dedup so each folder is listed once.
        by_folder: dict[str, tuple[str, str]] = {}
        for p in moved:
            m = metas.get(p.id)
            if not m or not p.folder_id:
                continue
            dir_path = m["path"].rsplit("/", 1)[0]
            by_folder[p.folder_id] = (dir_path, dir_path.rsplit("/", 1)[-1])
        out: list[tuple[str, str, str]] = []
        for fid, (dir_path, basename) in by_folder.items():
            try:
                if await self._is_dir_empty(dir_path):
                    out.append((fid, basename, space))
            except DsmError:
                continue  # best-effort — a probe failure just omits the offer
        return out

    @staticmethod
    def _record_placed(outcome, affected, space, dest_space, dest_dir, m, item_id,
                       copy, dest_filename) -> None:
        day = m["day"]
        dest_path = f"{dest_dir}/{dest_filename}"
        affected.add((space, day))
        affected.add((dest_space, day))
        if copy:
            outcome.created_ids.append(dest_path)  # DSM: path, not item id
        else:
            outcome.moved.append(
                PlacedItem(
                    id=item_id, space=space, folder_id=m["folder_id"], day=day,
                    src_path=m["path"], trash_path=dest_path,  # current location
                )
            )

    async def _place_renamed(
        self, src_path: str, dest_dir: str, filename: str, new_name: str, *, copy: bool
    ) -> None:
        # temp folder under dest so the copy/move never collides, then rename and
        # move into place. '#'-prefixed → hidden from the folder tree.
        tmp = f"{dest_dir}/#dup{_time.time_ns()}"
        await self._ensure_dir(tmp)
        try:
            await self._copymove([src_path], tmp, remove_src=not copy)
            await self._rename(f"{tmp}/{filename}", new_name)
            await self._copymove([f"{tmp}/{new_name}"], dest_dir, remove_src=True)
        finally:
            await self._delete_paths([tmp])

    async def delete(
        self,
        space: str,
        item_ids: list[str],
        on_progress: ProgressFn | None = None,
    ) -> DeleteOutcome:
        metas = await self._item_meta(space, item_ids)
        outcome = DeleteOutcome()
        affected: set[tuple[str, str]] = set()
        # One unique trash subfolder per delete op (avoids filename collisions).
        # 't' prefix: DSM rejects all-numeric folder names (code 400).
        trash_dir = f"{self.TRASH_ROOT}/t{_time.time_ns()}"
        await self._ensure_dir(trash_dir)
        src_paths = [metas[i]["path"] for i in item_ids if i in metas]
        await self._copymove_chunked(
            src_paths, trash_dir, remove_src=True, on_progress=on_progress
        )

        for item_id in item_ids:
            m = metas.get(item_id)
            if not m:
                continue
            affected.add((space, m["day"]))
            outcome.deleted.append(
                PlacedItem(
                    id=item_id, space=space, folder_id=m["folder_id"], day=m["day"],
                    src_path=m["path"], trash_path=f"{trash_dir}/{m['filename']}",
                )
            )
        # Hide the deleted ids immediately — Photos keeps returning them from the
        # folder/timeline filters until it reindexes the #trash move.
        _tombstone_items(self._sid, [p.id for p in outcome.deleted])
        _trash_cache_add([p.id for p in outcome.deleted])  # 증분 갱신(재스캔 회피)
        outcome.affected = sorted(affected)
        self._invalidate(affected)
        return outcome

    async def _reverse(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        """Move items from their current (trash_path) locations back to src.

        같은 원위치(폴더)로 돌아가는 항목들을 묶어 CopyMove 한 태스크로 처리 —
        대부분의 undo는 소수 폴더로 복귀하므로 500장 undo가 500태스크(수 분)에서
        폴더 수만큼으로 준다.
        """
        affected: set[tuple[str, str]] = set()
        total = len(placements)
        if on_progress:
            on_progress(0, total)
        groups: dict[str, list[PlacedItem]] = {}
        for p in placements:
            if not p.src_path or not p.trash_path:
                continue
            groups.setdefault(p.src_path.rsplit("/", 1)[0], []).append(p)
        done = 0
        for dest_dir, group in groups.items():
            for chunk in self._pack_copymove_chunks([p.trash_path for p in group]):
                await self._copymove(chunk, dest_dir, remove_src=True)
                done += len(chunk)
                if on_progress:
                    on_progress(min(done, total), total)
            affected.update((p.space, p.day) for p in group)
        self._invalidate(affected)
        return sorted(affected)

    async def place(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        # Undo move: the item returns to its old path — drop its tombstone so
        # the restored location shows it again without waiting for reindex.
        _untombstone_items(self._sid, [p.id for p in placements])
        return await self._reverse(placements, on_progress)

    async def restore(
        self, placements: list[PlacedItem], on_progress: ProgressFn | None = None
    ) -> Affected:
        _untombstone_items(self._sid, [p.id for p in placements])  # undo delete
        _trash_cache_remove([p.id for p in placements])  # 트래시에서 되돌아옴
        return await self._reverse(placements, on_progress)

    async def remove_items(self, item_ids: list[str]) -> Affected:
        # undo copy: item_ids are actually the created copies' absolute paths.
        await self._delete_paths(item_ids)
        invalidate_bucket_cache(self._sid)  # day unknown per path — clear all
        return []

    async def purge_trash(self) -> None:
        # Recursively delete the whole app trash folder; it is recreated by
        # _ensure_dir on the next delete. A missing folder (never deleted
        # anything yet / already purged) is not an error.
        try:
            await self._delete_paths([self.TRASH_ROOT])
        except DsmError as exc:
            if exc.code not in (408, 900):  # no such file/dir
                raise
        trash_cache_clear()

    async def _ensure_dir(self, path: str) -> None:
        # Create each level below the share root (/photo). Nested one-shot
        # creation with force_parent fails on '#'-prefixed segments (code 1002),
        # so build the path level by level; existing levels error out harmlessly.
        parts = path.split("/")  # ['', 'photo', '#trash', '<id>']
        for i in range(3, len(parts) + 1):
            parent = "/".join(parts[: i - 1])
            name = parts[i - 1]
            try:
                await self._dsm.call(
                    "SYNO.FileStation.CreateFolder", "create", version=2,
                    sid=self._sid,
                    # 숫자꼴 세그먼트 방어(위 create_folder와 동일 함정).
                    extra={
                        "folder_path": json.dumps(parent),
                        "name": json.dumps(name),
                    },
                )
            except DsmError as exc:
                # already-exists는 정상 경로. 그 외(권한/쿼터/경로)는 삼키면
                # 나중에 CopyMove가 엉뚱한 에러로 실패해 진단이 어려워지므로
                # 로그를 남긴다(동작은 기존과 동일하게 계속 시도).
                if exc.code not in (1100,):  # 1100 = create failed(존재 포함)
                    logger.warning("_ensure_dir %s/%s: %s", parent, name, exc)

    async def create_folder(
        self, space: str, name: str, parent_id: str | None = None
    ) -> PhotoFolder:
        target_id = parent_id
        if target_id is None:
            # 최상위 생성도 Foto API로 통일: FileStation 경유는 Photos가 재색인
            # 할 때까지 폴더 목록(Foto 인덱스)에 안 나타나 "생성됐다는데 안
            # 보임"이 됐다(2026-07-12 보고). 루트 폴더 id는 최상위 폴더들의
            # parent — 실 NAS: 팀 1, 개인 2. 목록이 비면 FileStation 폴백.
            kids = await self._list_children(space, 0)
            if kids:
                target_id = str(kids[0]["parent"])
        if target_id is not None:
            # 하위/최상위 폴더 생성: Browse.Folder create + target_id — 실 NAS
            # raw 검증(2026-07-03·07-12). Foto id를 즉시 돌려줘 재탐색이 없다.
            data = await self._dsm.call(
                _ns(space, "SYNO.Foto.Browse.Folder"),
                "create",
                version=1,
                sid=self._sid,
                extra={"target_id": int(target_id), "name": json.dumps(name)},
            )
            folder = data.get("folder") or {}
            invalidate_folder_cache(self._sid)
            pf = PhotoFolder(
                id=str(folder.get("id")),
                name=folder.get("name", f"/{name}"),
                space=space,
                parent_id=parent_id,
                depth=max(0, str(folder.get("name", "")).strip("/").count("/")),
            )
            _FOLDER_META.setdefault(self._sid, {})[pf.id] = (space, pf.name)
            return pf
        prefix = self._share_prefix(space)
        # JSON 인코딩 필수: 평문이면 "2024" 같은 숫자 이름을 DSM이 수식으로
        # 파싱해 400 (rename·검색과 동일 함정 — 2026-07-12 실 NAS 확인:
        # 평문 2024=400, json "2024"=성공. 글자 이름은 평문도 통과해 잠복).
        await self._dsm.call(
            "SYNO.FileStation.CreateFolder", "create", version=2, sid=self._sid,
            extra={"folder_path": json.dumps(prefix), "name": json.dumps(name)},
        )
        invalidate_folder_cache(self._sid)
        # Re-resolve via Photos so the new folder carries a Photos folder id
        # (FileStation create returns a filesystem path, not a Foto id).
        for f in await self.folders():
            if f.space == space and f.name.rstrip("/").endswith(name):
                return f
        return PhotoFolder(id=f"{prefix}/{name}", name=f"/{name}", space=space)

    # Synology sidecar dirs (@eaDir) and desktop droppings don't count as
    # folder contents — DSM's own UI treats such folders as empty too.
    _JUNK_ENTRIES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})

    async def remove_folder(self, folder_id: str) -> bool:
        # SAFETY: only EMPTY folders are removable — this also backs the
        # folder-view 삭제 버튼, so a photo-bearing folder must never vanish.
        # Emptiness is checked against the FILESYSTEM (FileStation.List), not
        # the Photos index: the index lags both ways — it kept counting
        # moved-out photos (blocking deletion of a truly empty folder,
        # 2026-07-04 실 NAS 사용자 보고) and it can miss just-added files
        # (which would delete them for good — photo share has no recycle bin).
        try:
            dest_dir, _ = await self._dest_dir(folder_id)
            if not await self._is_dir_empty(dest_dir):
                return False
        except DsmError:
            return False
        await self._delete_paths([dest_dir])
        invalidate_folder_cache(self._sid)
        # Photos keeps listing the folder until it reindexes → hide it now
        # (tombstone) so the tree drops it immediately after the toast.
        _REMOVED_FOLDERS.setdefault(self._sid, {})[str(folder_id)] = _time.monotonic()
        return True

    async def trash_folder(self, space: str, folder_id: str) -> dict:
        # 재귀 삭제 = 폴더를 통째로 앱 휴지통(/photo/#trash/t<ns>/)으로 이동.
        # 파일 단위로 풀지 않고 CopyMove 한 번으로 서브트리 전체를 옮겨(FileStation
        # 재귀), 하위 구조를 그대로 보존한다 → undo는 폴더를 원위치로 역이동.
        dest_dir, _ = await self._dest_dir(folder_id)
        basename = dest_dir.rsplit("/", 1)[-1]
        trash_dir = f"{self.TRASH_ROOT}/t{_time.time_ns()}"
        await self._ensure_dir(trash_dir)
        await self._copymove([dest_dir], trash_dir, remove_src=True)
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)
        # 폴더째 삭제는 어떤 아이템이 트래시로 갔는지 모름 → 캐시를 비워 다음
        # 조회가 (병렬) 재스캔으로 정확히 반영하게 한다.
        trash_cache_clear()
        # 트리에서 즉시 감춤(폴더 인덱스 지연 대비, remove_folder와 동일 패턴).
        _REMOVED_FOLDERS.setdefault(self._sid, {})[str(folder_id)] = _time.monotonic()
        return {
            "name": basename,
            "undo": {"trash_path": f"{trash_dir}/{basename}", "src_dir": dest_dir},
        }

    async def restore_folder(self, undo_payload: dict) -> None:
        parent = undo_payload["src_dir"].rsplit("/", 1)[0]
        await self._ensure_dir(parent)
        await self._copymove(
            [undo_payload["trash_path"]], parent, remove_src=True
        )
        _REMOVED_FOLDERS.pop(self._sid, None)  # 복원된 폴더가 다시 보이게
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)
        trash_cache_clear()  # 서브트리가 트래시에서 빠져나감 → 재스캔

    async def folder_conflicts(
        self, space: str, folder_ids: list[str], dest_folder_id: str
    ) -> list[tuple[str, str, int]]:
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        existing = await self._list_subdir_names(dest_dir)
        out: list[tuple[str, str, int]] = []
        for fid in folder_ids:
            src, _ = await self._dest_dir(fid)
            if src.rsplit("/", 1)[0] == dest_dir:
                continue  # 이미 대상 안 — 충돌 아님(no-op)
            name = src.rsplit("/", 1)[-1]
            if name in existing:
                extra = await self._folder_extra_count(src, f"{dest_dir}/{name}")
                out.append((fid, name, extra))
        return out

    async def move_folders(
        self,
        space: str,
        folder_ids: list[str],
        dest_folder_id: str,
        copy: bool,
        on_progress: ProgressFn | None = None,
        conflict_strategy: str = "skip",
    ) -> dict:
        dest_dir, _ = await self._dest_dir(dest_folder_id)
        taken = await self._list_subdir_names(dest_dir)
        plain: list[str] = []  # src dirs moving under their own name
        plain_names: list[str] = []
        renamed: list[tuple[str, str]] = []  # (src, new_name)
        merges: list[tuple[str, str]] = []  # (src, basename) folded into a twin
        for fid in folder_ids:
            src, _ = await self._dest_dir(fid)
            # Guard: 자기 자신/자기 하위로의 이동은 무한 중첩 — 차단.
            if dest_dir == src or dest_dir.startswith(src + "/"):
                raise DsmError(
                    100, f"'{src.rsplit('/', 1)[-1]}' 폴더를 자기 자신(하위) 안으로 옮길 수 없습니다."
                )
            if src.rsplit("/", 1)[0] == dest_dir and not copy:
                continue  # 이미 대상 폴더 안 — no-op
            name = src.rsplit("/", 1)[-1]
            if name in taken:
                # 같은 이름 폴더가 대상에 있음: skip 건너뜀 / rename name_1 /
                # merge 내용 합치기(재귀).
                if conflict_strategy == "rename":
                    new_name = self._unique_dir_name(taken, name)
                    taken.add(new_name)
                    renamed.append((src, new_name))
                elif conflict_strategy == "merge":
                    merges.append((src, name))
                continue
            taken.add(name)
            plain.append(src)
            plain_names.append(name)

        if plain:
            # CopyMove는 디렉터리도 재귀 이동/복사한다 (실 NAS 검증 —
            # 2026-07-03 MobileBackup 평탄화 작업에서 대량 실사용). 폴더당 사진이
            # 수천 장이면 태스크가 오래 걸리므로, 폴더 수(0/1)가 아니라 바이트
            # 진행률을 퍼센트(0~100)로 보고해 진행바가 움직이게 한다.
            def _task_prog(frac: float) -> None:
                if on_progress:
                    on_progress(min(int(frac * 100), 100), 100)

            await self._copymove_chunked(
                plain,
                dest_dir,
                remove_src=not copy,
                on_progress=None,
                on_task_progress=_task_prog,
            )
        for src, new_name in renamed:
            await self._place_renamed(
                src, dest_dir, src.rsplit("/", 1)[-1], new_name, copy=copy
            )
        merge_undo: list[dict] = []
        merge_names: list[str] = []
        for src, base in merges:
            undo_entry = await self._merge_dir(src, f"{dest_dir}/{base}", copy=copy)
            merge_undo.append(undo_entry)
            merge_names.append(base)

        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)
        if not copy:
            # 이동된 폴더의 경로 캐시는 낡음 — 남겨두면 후속 파일 작업이 옛
            # 경로로 CopyMove 될 수 있어 제거(재탐색 시 재적재).
            metas = _FOLDER_META.get(self._sid, {})
            for fid in folder_ids:
                metas.pop(str(fid), None)
        # NOTE: 이동한 폴더는 tombstone하지 않는다 (2026-07-04 실 NAS 보고 — 재색인이
        # 폴더 id를 유지하면 대상 위치까지 숨는다). 원본 잔상은 프론트 resettle로 정리.
        names = plain_names + [nn for _, nn in renamed] + merge_names
        undo = (
            [{"src": s, "dest": f"{dest_dir}/{n}"} for s, n in zip(plain, plain_names)]
            + [{"src": s, "dest": f"{dest_dir}/{nn}"} for s, nn in renamed]
            + merge_undo
        )
        return {"names": names, "undo": undo}

    async def _merge_dir(self, src_dir: str, dest_dir: str, *, copy: bool) -> dict:
        """Fold ``src_dir``'s contents into the same-named ``dest_dir``.

        Files: non-clashing ones move/copy in; a name clash keeps the existing
        destination file and leaves the source one alone (사용자 결정). Sub-
        folders: a same-named twin recurses (merge), otherwise the whole subtree
        moves/copies in one shot. In move mode the source folder is deleted once
        fully emptied (병합 완료). Returns an undo entry for revert_move_folders.
        """
        await self._ensure_dir(dest_dir)
        dest_names = await self._list_filenames(dest_dir)
        moved: list[dict] = []  # move-undo: [{"from": dest, "to": src}]
        created: list[str] = []  # copy-undo: paths to delete
        children: list[dict] = []  # nested merge undo entries
        move_files: list[tuple[str, str]] = []
        for entry in await self._list_entries(src_dir):
            name = entry.get("name", "")
            if name.startswith("@") or name in self._JUNK_ENTRIES:
                continue
            src_path = f"{src_dir}/{name}"
            dest_path = f"{dest_dir}/{name}"
            if entry.get("isdir"):
                if name in dest_names:
                    children.append(
                        await self._merge_dir(src_path, dest_path, copy=copy)
                    )
                else:
                    await self._copymove([src_path], dest_dir, remove_src=not copy)
                    (created if copy else moved).append(
                        dest_path if copy else {"from": dest_path, "to": src_path}
                    )
            elif name in dest_names:
                continue  # 파일 충돌 → 기존 유지, 소스는 그대로 둠
            else:
                move_files.append((src_path, dest_path))
        if move_files:
            await self._copymove_chunked(
                [s for s, _ in move_files], dest_dir, remove_src=not copy,
                on_progress=None,
            )
            for s, d in move_files:
                (created if copy else moved).append(
                    d if copy else {"from": d, "to": s}
                )
        emptied = False
        if not copy and await self._is_dir_empty(src_dir):
            await self._delete_paths([src_dir])
            emptied = True
        return {
            "kind": "merge_copy" if copy else "merge",
            "moved": moved,
            "created": created,
            "children": children,
            "src_dir": src_dir,
            "emptied": emptied,
        }

    async def revert_move_folders(self, undo_payload: list, copy: bool) -> None:
        # Entries are heterogeneous: plain move/copy (whole subtree, no "kind")
        # and merge/merge_copy (per-file, recursive). Dispatch per entry so a
        # single op can mix them (merge strategy folds clashers, moves the rest).
        for e in undo_payload:
            await self._revert_folder_entry(e, copy)
        if not copy:
            # 되돌린 원본 폴더가 트리에 다시 보여야 한다 — 혹 Photos가 폴더 id를
            # 재사용하면 tombstone이 복원본을 가릴 수 있으므로 전부 해제.
            _REMOVED_FOLDERS.pop(self._sid, None)
        invalidate_folder_cache(self._sid)
        invalidate_bucket_cache(self._sid)

    async def _revert_folder_entry(self, e: dict, copy: bool) -> None:
        kind = e.get("kind", "move")
        if kind == "merge_copy":
            if e.get("created"):
                await self._delete_paths(e["created"])
            for child in e.get("children", []):
                await self._revert_folder_entry(child, True)
        elif kind == "merge":
            # Move each merged file back to its source folder (recreating the
            # deleted source dir first), then recurse into nested merges.
            for mv in e.get("moved", []):
                parent = mv["to"].rsplit("/", 1)[0]
                await self._ensure_dir(parent)
                await self._copymove([mv["from"]], parent, remove_src=True)
            for child in e.get("children", []):
                await self._revert_folder_entry(child, False)
        elif copy:  # 통째 복사 취소: 사본 폴더 영구 삭제
            await self._delete_paths([e["dest"]])
        else:  # 통째 이동 취소: 원위치로 역이동
            parent = e["src"].rsplit("/", 1)[0]
            await self._copymove([e["dest"]], parent, remove_src=True)

    def _invalidate(self, affected: set[tuple[str, str]]) -> None:
        for space, _ in affected:
            invalidate_bucket_cache(self._sid, space)

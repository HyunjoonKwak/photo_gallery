"""Regression: photo move (ops/move) crashed with
`_copymove_chunked() got an unexpected keyword argument 'overwrite'` because the
chunked helper didn't accept/forward the overwrite flag that move() passes for
the "overwrite" conflict strategy. Guard the contract without a live DSM.
"""

import asyncio

from app.photos.dsm_source import DsmPhotoSource


def test_copymove_chunked_forwards_overwrite():
    src = DsmPhotoSource.__new__(DsmPhotoSource)  # skip __init__ (no DSM needed)
    calls: list[dict] = []

    async def fake_copymove(paths, dest_dir, *, remove_src, overwrite=False, progress_cb=None):
        calls.append({"paths": list(paths), "remove_src": remove_src, "overwrite": overwrite})

    src._copymove = fake_copymove  # type: ignore[attr-defined]

    paths = [f"/vol/a/{i}.jpg" for i in range(30)]  # spans 2 chunks (COPYMOVE_CHUNK=25)
    asyncio.run(
        src._copymove_chunked(
            paths, "/vol/dest", remove_src=True, on_progress=None, overwrite=True
        )
    )

    assert calls, "expected _copymove to be invoked"
    assert all(c["overwrite"] is True for c in calls)
    assert all(c["remove_src"] is True for c in calls)
    assert sum(len(c["paths"]) for c in calls) == 30


def test_copymove_chunked_overwrite_defaults_false():
    src = DsmPhotoSource.__new__(DsmPhotoSource)
    calls: list[dict] = []

    async def fake_copymove(paths, dest_dir, *, remove_src, overwrite=False, progress_cb=None):
        calls.append({"overwrite": overwrite})

    src._copymove = fake_copymove  # type: ignore[attr-defined]
    asyncio.run(
        src._copymove_chunked(["/vol/a/1.jpg"], "/vol/dest", remove_src=False, on_progress=None)
    )
    assert calls and calls[0]["overwrite"] is False

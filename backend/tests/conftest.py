"""Shared test fixtures.

dsm_source keeps process-global caches (trash ids, bucket L1, sid→account) so
the running app can share them across sessions — but tests must not leak state
into each other. Reset them before every test.
"""

import pytest

from app.photos import dsm_source


@pytest.fixture(autouse=True)
def _reset_photo_caches():
    dsm_source.trash_cache_clear()
    dsm_source._BUCKET_CACHE.clear()
    dsm_source._BUCKET_SCANNING.clear()
    dsm_source._SID_ACCOUNT.clear()
    dsm_source._VIDEO_CACHE.clear()
    dsm_source._FOLDER_META.clear()
    dsm_source._TOP_FOLDER_CACHE.clear()
    dsm_source._REMOVED_FOLDERS.clear()
    dsm_source._REMOVED_ITEMS.clear()
    yield

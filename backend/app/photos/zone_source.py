"""1차 구역(기기 백업 zone) 소스 — 로그인 사용자 본인의, Synology Photos 인덱스
밖 폴더를 FileStation으로 읽는다.

``HomesPhotoSource``와 달리 개인/공용 Foto prefix를 **하이재킹하지 않는다**:
zone에서 사진을 골라 옮기는 목적지(2차)는 본인의 개인 Photos(`/home/Photos`)
이므로, `_share_prefix("personal")`은 그대로 두어야 `_dest_dir(개인 Foto id)`가
zone 안이 아니라 올바른 개인 Photos 경로로 계산된다.

``_FsRootMixin``이 zone 루트 하위 브라우징·썸네일·이동/삭제의 경로형 id 처리를
담당하고, 목적지(개인/공용 Foto)와 이동/undo 파이프라인은 ``DsmPhotoSource``를
그대로 상속한다. ``folders(None)``은 mixin 기본대로 **zone 루트 하위만** 반환
하므로(개인/공용 Foto 폴더를 섞지 않음) 프론트 루트 필터가 1차만 보여준다.
"""

from __future__ import annotations

from ..dsm.client import DsmClient
from .dsm_source import DsmPhotoSource
from .homes_source import _FsRootMixin


class ZonePhotoSource(_FsRootMixin, DsmPhotoSource):
    def __init__(self, dsm: DsmClient, sid: str, root_path: str) -> None:
        super().__init__(dsm, sid)
        self._root = root_path

    @property
    def _root_path(self) -> str:
        return self._root

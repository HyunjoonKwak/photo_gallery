"""System endpoints: expose the SYNO.API.Info probe so we can verify, against
the real NAS, which DSM APIs/paths/versions are actually available.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..dsm.errors import DsmError
from ..schemas import ApiInfoResponse, EndpointInfo
from ..session_store import Session
from .deps import get_current_session, get_dsm_client

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info", response_model=ApiInfoResponse)
async def api_info(
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
    _session: Session = Depends(get_current_session),
) -> ApiInfoResponse:
    """Resolve the core APIs via SYNO.API.Info and report availability."""
    try:
        resolved = await dsm.query_api_info(refresh=True)
    except DsmError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    endpoints = [
        EndpointInfo(
            api=api,
            path=resolved[api].path if api in resolved else "",
            min_version=resolved[api].min_version if api in resolved else 0,
            max_version=resolved[api].max_version if api in resolved else 0,
            available=api in resolved,
        )
        for api in DsmClient.CORE_APIS
    ]
    return ApiInfoResponse(
        dsm_webapi_base=settings.dsm_webapi_base, endpoints=endpoints
    )

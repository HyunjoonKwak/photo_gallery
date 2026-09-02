"""System endpoints: expose the SYNO.API.Info probe so we can verify, against
the real NAS, which DSM APIs/paths/versions are actually available.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..schemas import ApiInfoResponse, EndpointInfo, GalleryCapabilitiesResponse
from ..session_store import Session
from ..write_policy import capabilities_for
from .deps import get_current_session, get_dsm_client

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info", response_model=ApiInfoResponse)
async def api_info(
    settings: Settings = Depends(get_settings),
    dsm: DsmClient = Depends(get_dsm_client),
    _session: Session = Depends(get_current_session),
) -> ApiInfoResponse:
    """Resolve the core APIs via SYNO.API.Info and report availability.

    DSM failures propagate to the app-wide ``DsmError`` handler (session-invalid
    codes → 401, everything else → 502).
    """
    capabilities = capabilities_for(settings, _session.role)
    capability_response = GalleryCapabilitiesResponse(**capabilities.__dict__)

    if settings.mock_mode:
        # No NAS to probe — report every core API as (mock) available so the
        # panel stays meaningful during NAS-free development.
        return ApiInfoResponse(
            dsm_webapi_base="(mock)",
            endpoints=[
                EndpointInfo(
                    api=api, path="(mock)", min_version=1, max_version=1, available=True
                )
                for api in DsmClient.CORE_APIS
            ],
            gallery_write_mode=settings.gallery_write_mode,
            capabilities=capability_response,
        )

    resolved = await dsm.query_api_info(refresh=True)

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
        dsm_webapi_base=settings.dsm_webapi_base,
        endpoints=endpoints,
        gallery_write_mode=settings.gallery_write_mode,
        capabilities=capability_response,
    )

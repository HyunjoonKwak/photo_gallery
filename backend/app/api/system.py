"""System endpoints: expose the SYNO.API.Info probe so we can verify, against
the real NAS, which DSM APIs/paths/versions are actually available.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, get_settings
from ..dsm.client import DsmClient
from ..schemas import ApiInfoResponse, EndpointInfo
from ..session_store import Session
from .deps import get_current_session, get_dsm_client

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/pool-debug")
async def pool_debug(dsm: DsmClient = Depends(get_dsm_client)) -> dict:
    """TEMP diagnostic: dump the httpx connection-pool internals so we can see
    whether pool slots are leaking (many connections stuck/closed but counted).
    No auth on purpose so it can be sampled during a fault. Remove after."""
    out: dict = {}
    try:
        pool = dsm._http._transport._pool  # httpcore.AsyncConnectionPool
        conns = list(pool.connections)
        out["num_connections"] = len(conns)
        out["max_connections"] = getattr(pool, "_max_connections", None)

        def describe(c) -> dict:
            d: dict = {}
            for attr in ("is_closed", "is_available", "is_idle", "has_expired"):
                fn = getattr(c, attr, None)
                try:
                    d[attr] = fn() if callable(fn) else None
                except Exception as e:  # noqa: BLE001
                    d[attr] = f"err:{type(e).__name__}"
            inner = getattr(c, "_connection", None)
            state = getattr(inner, "_state", None)
            d["state"] = state.__class__.__name__ if state is not None else None
            d["req_on_conn"] = getattr(inner, "_request_count", None)
            return d

        out["connections"] = [describe(c) for c in conns[:150]]
        # pending pool requests waiting for a slot
        reqs = getattr(pool, "_requests", None)
        out["pending_requests"] = len(reqs) if reqs is not None else None
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
    return out


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
        dsm_webapi_base=settings.dsm_webapi_base, endpoints=endpoints
    )

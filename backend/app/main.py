"""FastAPI application entrypoint.

Creates a shared httpx client + DSM client during the app lifespan, wires the
API routers, configures CORS for the Vite dev server, and (in production)
serves the built frontend as static files.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

from .api import auth, dedup, ops, photos, system, zones
from .config import Settings, get_settings
from .db import init_db
from .dsm.client import DsmClient
from .dsm.errors import SESSION_INVALID_CODES, DsmError
from .session_store import delete_session, purge_expired


class SpaStaticFiles(StaticFiles):
    """Serve the built SPA with cache headers tuned for reliable PWA updates.

    The entry points (index.html, sw.js, the web manifest) must always be
    revalidated so a new deploy actually reaches installed clients — otherwise
    a stale service worker/proxy can pin a device to old JS indefinitely. The
    content-hashed files under /assets/ are immutable and cached for a year.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        req_path = scope.get("path", "") if isinstance(scope, dict) else ""
        if (
            req_path in ("/", "/sw.js")
            or req_path.endswith(".html")
            or req_path.endswith(".webmanifest")
        ):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        elif "/assets/" in req_path:
            response.headers.setdefault(
                "Cache-Control", "public, max-age=31536000, immutable"
            )
        return response


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_db(settings.sqlite_path)
    purge_expired(settings.sqlite_path)

    # Bound the connection pool so a leaked/stuck connection can't silently
    # starve every request: `pool` timeout fails fast (surfaces as a quick error
    # instead of a 30s hang), and `keepalive_expiry` recycles idle connections
    # so stale keep-alives left over after a DSM/Photos restart aren't reused.
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.dsm_timeout_seconds, pool=5.0),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,
            keepalive_expiry=30.0,
        ),
        verify=settings.dsm_verify_tls,
        follow_redirects=True,
    )
    app.state.http_client = http
    app.state.dsm_client = DsmClient(settings.dsm_webapi_base, http)
    try:
        yield
    finally:
        await http.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="NAS Photo Organizer", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DsmError)
    async def dsm_error_handler(request: Request, exc: DsmError) -> JSONResponse:
        """Turn uncaught DSM failures into HTTP responses.

        A dead sid (session timeout / interrupted / invalid) must surface as
        401 so the browser re-authenticates — and we drop the now-useless app
        session on the way out. Every other DSM failure is an upstream/gateway
        problem (502). Routers that need bespoke handling (e.g. login mapping
        bad-credential codes to 401) catch DsmError themselves before it reaches
        here.
        """
        current: Settings = get_settings()
        if exc.code in SESSION_INVALID_CODES:
            token = request.cookies.get(current.session_cookie_name)
            if token:
                delete_session(current.sqlite_path, token)
            response = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": str(exc)}
            )
            response.delete_cookie(current.session_cookie_name, path="/")
            return response
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)}
        )

    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(photos.router)
    app.include_router(ops.router)
    app.include_router(dedup.router)
    app.include_router(zones.router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Serve the built frontend (production) if a dist directory is configured.
    if settings.frontend_dist and os.path.isdir(settings.frontend_dist):
        app.mount(
            "/",
            SpaStaticFiles(directory=settings.frontend_dist, html=True),
            name="frontend",
        )

    return app


app = create_app()

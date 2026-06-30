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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import auth, system
from .config import get_settings
from .db import init_db
from .dsm.client import DsmClient
from .session_store import purge_expired


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_db(settings.sqlite_path)
    purge_expired(settings.sqlite_path)

    http = httpx.AsyncClient(
        timeout=settings.dsm_timeout_seconds,
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

    app.include_router(auth.router)
    app.include_router(system.router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # Serve the built frontend (production) if a dist directory is configured.
    if settings.frontend_dist and os.path.isdir(settings.frontend_dist):
        app.mount(
            "/",
            StaticFiles(directory=settings.frontend_dist, html=True),
            name="frontend",
        )

    return app


app = create_app()

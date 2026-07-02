"""Application configuration loaded from environment / .env.

Credentials (DSM account/password) are NEVER stored here — they are supplied
per-login by the user and exchanged for a DSM session id (SID) at runtime.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- DSM connection (no credentials here) ---
    dsm_base_url: str = Field(
        default="http://localhost",
        description="DSM base URL without port, e.g. https://nas.example.com",
    )
    dsm_port: int = Field(default=5000, description="DSM web port (5000 http / 5001 https)")
    # When DSM uses a self-signed certificate, set to False to skip TLS verification.
    dsm_verify_tls: bool = Field(default=True)
    dsm_timeout_seconds: float = Field(default=30.0)

    # --- App session ---
    # Cookies carry an opaque random token (secrets.token_urlsafe), so no signing
    # secret is needed — the token is looked up server-side in the session table.
    session_cookie_name: str = Field(default="nasphoto_session")
    session_ttl_seconds: int = Field(default=60 * 60 * 8)  # 8h
    # Set True when served over HTTPS (DSM reverse proxy). Cookie -> Secure flag.
    cookie_secure: bool = Field(default=False)

    # --- Login throttling (app-level, protects against DSM Auto Block lockout) ---
    login_max_attempts: int = Field(default=5)
    login_window_seconds: int = Field(default=600)  # 10 minutes

    # --- Dev mock mode (no NAS required) ---
    # True -> login accepts any credentials and photo APIs serve deterministic
    # fake data, so the frontend can be developed without a reachable DSM.
    # NEVER enable in production.
    mock_mode: bool = Field(default=False)

    # --- Storage ---
    sqlite_path: str = Field(default="./data/app.db")

    # Built frontend (Vite dist) served as static files in production.
    # Empty -> API-only mode (dev uses the Vite dev server instead).
    frontend_dist: str = Field(default="")

    # --- CORS (dev: Vite dev server) ---
    cors_origins: str = Field(default="http://localhost:5173")

    @property
    def dsm_webapi_base(self) -> str:
        """Base URL for DSM Web API endpoints (without trailing slash)."""
        base = self.dsm_base_url.rstrip("/")
        return f"{base}:{self.dsm_port}/webapi"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

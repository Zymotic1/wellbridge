"""
Application settings loaded from environment variables via pydantic-settings.

.env file resolution order (first match wins):
  1. backend/.env          (set WELLBRIDGE_ENV_FILE to override)
  2. wellbridge/.env       (project root — most convenient for local dev)

DEV MODE: If auth0_domain, openai_api_key, or supabase_url are not set,
the server still starts but protected endpoints return a 503 with a clear
message. Set WELLBRIDGE_DEV_MODE=true to also bypass JWT verification and
use a fixed dev identity (safe only for local testing).
"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# Resolve candidate .env paths regardless of the cwd the server is launched from
_BACKEND_DIR = Path(__file__).parent
_PROJECT_ROOT = _BACKEND_DIR.parent

_ENV_FILES = [
    str(_BACKEND_DIR / ".env"),       # backend/.env  (takes precedence)
    str(_PROJECT_ROOT / ".env"),      # wellbridge/.env  (project root)
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",               # Ignore unknown env vars gracefully
    )

    # --- Auth0 ---
    auth0_domain: str = ""
    auth0_audience: str = ""

    # --- OpenAI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4-turbo"
    openai_embedding_model: str = "text-embedding-3-small"

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""       # Public anon key — used for user-scoped JWT queries
    supabase_service_key: str = ""    # Service role — NEVER expose to frontend

    # --- Azure Document Intelligence (optional) ---
    azure_doc_intelligence_endpoint: str = ""
    azure_doc_intelligence_key: str = ""

    # --- LlamaParse (document / audio / image parsing) ---
    llama_cloud_api_key: str = ""

    # --- Google Calendar (optional) ---
    google_calendar_credentials_json: str = ""

    # --- Epic MyChart / SMART on FHIR ---
    # Register your app at https://open.epic.com → My Apps → Create App
    # App type: Patient-Facing (Standalone Patient Launch) | Platform: Web
    # Redirect URIs: http://localhost:3000/epic/callback  (dev)
    #                https://app.wellbridge.health/epic/callback  (prod)
    # Scopes: openid fhirUser offline_access patient/Patient.read
    #         patient/MedicationRequest.read patient/Condition.read
    #         patient/Appointment.read patient/Encounter.read
    #         patient/AllergyIntolerance.read patient/Observation.read
    #         patient/DocumentReference.read
    # Client ID is issued immediately for non-production sandbox use.
    # Production access requires Epic's app validation review (~4-8 weeks).
    epic_client_id: str = ""
    epic_redirect_uri: str = "http://localhost:3000/epic/callback"
    # Generate a Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    epic_token_encryption_key: str = ""

    # --- Admin (sync trigger endpoints) ---
    # Set to any non-empty secret string; required to call POST /admin/sync/*
    admin_secret: str = ""

    # --- Dev / runtime config ---
    environment: str = "development"
    log_level: str = "INFO"
    wellbridge_dev_mode: bool = False  # Set to true to bypass JWT in local dev

    # -------------------------------------------------------------------------
    # Computed properties
    # -------------------------------------------------------------------------

    @property
    def jwks_uri(self) -> str:
        return f"https://{self.auth0_domain}/.well-known/jwks.json"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_configured(self) -> bool:
        return bool(self.auth0_domain and self.auth0_audience)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def llama_parse_configured(self) -> bool:
        return bool(self.llama_cloud_api_key)

    @property
    def epic_configured(self) -> bool:
        return bool(self.epic_client_id and self.epic_token_encryption_key)

    def require_auth(self) -> None:
        """Call at the start of any endpoint that needs Auth0. Raises 503 in dev if unconfigured."""
        if not self.auth_configured and not self.wellbridge_dev_mode:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=503,
                detail=(
                    "Auth0 is not configured. "
                    "Set AUTH0_DOMAIN and AUTH0_AUDIENCE in your .env file, "
                    "or set WELLBRIDGE_DEV_MODE=true to bypass auth for local testing."
                ),
            )

    def require_openai(self) -> None:
        """Call before any LLM call. Raises 503 if OPENAI_API_KEY is not set."""
        if not self.openai_configured:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=503,
                detail="OPENAI_API_KEY is not set. Add it to your .env file.",
            )

    def require_supabase(self) -> None:
        """Call before any DB call. Raises 503 if Supabase is not configured."""
        if not self.supabase_configured:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=503,
                detail=(
                    "Supabase is not configured. "
                    "Set SUPABASE_URL and SUPABASE_SERVICE_KEY in your .env file."
                ),
            )


@lru_cache()
def get_settings() -> Settings:
    s = Settings()
    # Startup diagnostics — printed once, not an exception
    missing = []
    if not s.auth0_domain:      missing.append("AUTH0_DOMAIN")
    if not s.auth0_audience:    missing.append("AUTH0_AUDIENCE")
    if not s.openai_api_key:    missing.append("OPENAI_API_KEY")
    if not s.supabase_url:      missing.append("SUPABASE_URL")
    if not s.supabase_service_key: missing.append("SUPABASE_SERVICE_KEY")
    if missing:
        import logging
        log = logging.getLogger("wellbridge.config")
        log.warning(
            "WellBridge starting in PARTIAL mode — missing env vars: %s. "
            "Copy .env.example to .env and fill in values. "
            "Set WELLBRIDGE_DEV_MODE=true to bypass auth for local testing.",
            ", ".join(missing),
        )
    return s

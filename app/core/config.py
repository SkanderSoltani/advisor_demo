"""Application configuration, loaded from environment variables / .env."""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """All runtime settings. Every value can be overridden via env var of the same name."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ---
    APP_NAME: str = "Transition Studio"
    ENV: Literal["dev", "test", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    DEMO_MODE: bool = True

    # --- database ---
    DATABASE_URL: str = f"sqlite:///{REPO_ROOT / 'data' / 'transition_studio.db'}"

    # --- auth (mock JWT) ---
    JWT_SECRET: str = "change-me-demo-only-secret-not-for-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 12 * 60

    # --- CORS ---
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- synthetic data ---
    DATA_DIR: Path = REPO_ROOT / "data" / "synthetic"
    SYNTHETIC_SEED: int = 20240501
    # Fixed "as-of" date so the demo is fully reproducible regardless of the wall clock.
    AS_OF_DATE: date = date(2026, 10, 30)
    PRICE_HISTORY_YEARS: int = 5
    UNIVERSE_SIZE: int = 300
    # Editable target-model catalog (products + model weights); reloaded at startup.
    MODELS_FILE: Path = REPO_ROOT / "data" / "models" / "target_models.json"
    # Client book master copy (clients, accounts, lots, history). See app/db/book_store.py.
    BOOK_FILE: Path = REPO_ROOT / "data" / "book" / "book.json"
    BOOK_EXTRA_CLIENTS: int = 91  # generated on top of the 9 hand-written households
    BOOK_TARGET_AUM: float = 1_500_000_000.0  # whole-book AUM the generator aims for

    # --- analytics ---
    ANALYTICS_PROVIDER: Literal["random", "aladdin"] = "random"
    # Point-in-time book / client analytics (app/risk_analytics): source and saved files.
    RISK_ANALYTICS_PROVIDER: Literal["mock", "aladdin", "bloomberg"] = "mock"
    RISK_SNAPSHOT_FILE: Path = REPO_ROOT / "data" / "analytics" / "risk_snapshot.json"
    SECURITY_MASTER_FILE: Path = REPO_ROOT / "data" / "analytics" / "security_master.json"

    # --- LLM ---
    LLM_PROVIDER: Literal["mock", "anthropic"] = "mock"
    LLM_MODEL: str = "claude-opus-5-5"
    # Server-side refusal fallback (Claude API beta). Disable if LLM_MODEL does not support it.
    LLM_SERVER_FALLBACK: bool = True
    ANTHROPIC_API_KEY: str | None = None

    # --- Plaid (sandbox only) ---
    PLAID_CLIENT_ID: str | None = None
    PLAID_SECRET: str | None = None
    PLAID_ENV: Literal["sandbox"] = "sandbox"

    # --- uploads ---
    MAX_UPLOAD_MB: int = 10

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip().startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached settings."""
    return Settings()

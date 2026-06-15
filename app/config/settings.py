"""
TrueBuild Integration Platform — Configuration Settings.

All configuration is loaded from environment variables via Pydantic Settings.
Never hardcode secrets. Use .env files for local development.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────
    APP_NAME: str = "TrueBuild Integration Platform"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    SECRET_KEY: str = Field(..., description="Application secret key for signing")

    # ── Odoo Online ──────────────────────────────────────────────────────
    ODOO_URL: str = Field(..., description="Odoo instance URL, e.g. https://truebuild.odoo.com")
    ODOO_DB: str = Field(..., description="Odoo database name (usually the subdomain)")
    ODOO_USERNAME: str = Field(..., description="Odoo user email for XML-RPC")
    ODOO_PASSWORD: str = Field(..., description="Odoo API password (set via Change Password)")
    ODOO_TIMEOUT: int = Field(default=30, description="XML-RPC call timeout in seconds")

    # ── WooCommerce ──────────────────────────────────────────────────────
    WOO_URL: str = Field(..., description="WooCommerce store URL, e.g. https://truebuild.com.au")
    WOO_CONSUMER_KEY: str = Field(..., description="WooCommerce REST API consumer key")
    WOO_CONSUMER_SECRET: str = Field(..., description="WooCommerce REST API consumer secret")
    WOO_WEBHOOK_SECRET: str = Field(..., description="WooCommerce webhook signing secret")
    WOO_API_VERSION: str = Field(default="wc/v3", description="WooCommerce API version")
    WOO_TIMEOUT: int = Field(default=30, description="WooCommerce API timeout in seconds")
    WOO_VERIFY_SSL: bool = Field(default=True, description="Verify SSL for WooCommerce API")

    # ── PostgreSQL ───────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        ...,
        description="PostgreSQL connection string, e.g. postgresql://user:pass@localhost:5432/truebuild",
    )
    DB_POOL_SIZE: int = Field(default=10, description="SQLAlchemy connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=20, description="Max overflow connections")
    DB_POOL_TIMEOUT: int = Field(default=30, description="Connection pool timeout in seconds")
    DB_ECHO: bool = Field(default=False, description="Echo SQL statements for debugging")

    # ── Redis ────────────────────────────────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for Celery broker and caching",
    )
    REDIS_CACHE_TTL: int = Field(default=300, description="Default cache TTL in seconds")

    # ── Celery ───────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = Field(default="", description="Celery broker URL (defaults to REDIS_URL)")
    CELERY_RESULT_BACKEND: str = Field(default="", description="Celery result backend (defaults to REDIS_URL)")

    # ── Sync Configuration ───────────────────────────────────────────────
    PRODUCT_SYNC_INTERVAL_SECONDS: int = Field(default=300, description="Product sync interval (5 min)")
    INVENTORY_SYNC_INTERVAL_SECONDS: int = Field(default=300, description="Inventory sync interval (5 min)")
    SYNC_BATCH_SIZE: int = Field(default=50, description="Number of records per sync batch")

    # ── Tax (Australia GST) ──────────────────────────────────────────────
    GST_RATE: float = Field(default=0.10, description="Australian GST rate (10%)")
    GST_TAX_CLASS: str = Field(default="GST", description="WooCommerce tax class name")

    # ── Retry Policy ─────────────────────────────────────────────────────
    MAX_RETRIES: int = Field(default=4, description="Maximum retry attempts before dead letter")
    RETRY_DELAYS_SECONDS: list[int] = Field(
        default=[60, 300, 900, 3600],
        description="Retry delay schedule: 1min, 5min, 15min, 1hr",
    )

    # ── Rate Limiting ────────────────────────────────────────────────────
    RATE_LIMIT_REQUESTS: int = Field(default=100, description="Max requests per window")
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, description="Rate limit window in seconds")
    WEBHOOK_RATE_LIMIT_REQUESTS: int = Field(default=30, description="Webhook endpoint rate limit")
    WEBHOOK_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, description="Webhook rate limit window")

    # ── CORS ─────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = Field(default=["*"], description="Allowed CORS origins")

    @field_validator("CELERY_BROKER_URL", mode="before")
    @classmethod
    def default_celery_broker(cls, v: str, info) -> str:  # noqa: N805
        if not v:
            return info.data.get("REDIS_URL", "redis://localhost:6379/0")
        return v

    @field_validator("CELERY_RESULT_BACKEND", mode="before")
    @classmethod
    def default_celery_backend(cls, v: str, info) -> str:  # noqa: N805
        if not v:
            return info.data.get("REDIS_URL", "redis://localhost:6379/0")
        return v

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()

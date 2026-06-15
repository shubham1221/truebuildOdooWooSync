"""
TrueBuild Integration Platform — Webhook & Sync Schemas.

Pydantic V2 schemas for webhook payloads and sync status responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Webhook Schemas ──────────────────────────────────────────────────────────


class WebhookPayload(BaseModel):
    """Generic WooCommerce webhook payload."""

    id: int | None = None
    status: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class WebhookResponse(BaseModel):
    """Response returned by webhook endpoints."""

    status: str = "accepted"
    message: str = ""
    woo_order_id: int | None = None


# ── Sync Schemas ─────────────────────────────────────────────────────────────


class SyncStatusResponse(BaseModel):
    """Overall sync status response."""

    product_sync: SyncTypeStatus | None = None
    inventory_sync: SyncTypeStatus | None = None
    order_sync: SyncTypeStatus | None = None
    total_products_mapped: int = 0
    total_orders_mapped: int = 0
    total_customers_mapped: int = 0
    pending_failed_jobs: int = 0
    dead_letter_jobs: int = 0


class SyncTypeStatus(BaseModel):
    """Status of a specific sync type."""

    last_sync_at: datetime | None = None
    last_status: str = "unknown"
    total_synced: int = 0
    total_failed: int = 0


class SyncLogResponse(BaseModel):
    """API response for a sync log entry."""

    id: int
    event_type: str
    entity_type: str
    entity_id: str | None
    direction: str
    status: str
    message: str | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FailedJobResponse(BaseModel):
    """API response for a failed job."""

    id: int
    job_type: str
    entity_type: str | None
    entity_id: str | None
    error_message: str | None
    retry_count: int
    max_retries: int
    next_retry_at: datetime | None
    status: str
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ManualSyncRequest(BaseModel):
    """Request body for manual sync triggers."""

    force: bool = False
    sku: str | None = None
    woo_order_id: int | None = None


class HealthCheckResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    database: dict[str, Any] = Field(default_factory=dict)
    redis: dict[str, Any] = Field(default_factory=dict)
    odoo: dict[str, Any] = Field(default_factory=dict)
    woocommerce: dict[str, Any] = Field(default_factory=dict)
    version: str = ""

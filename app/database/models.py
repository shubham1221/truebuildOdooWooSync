"""
TrueBuild Integration Platform — Database ORM Models.

All mapping and tracking tables for the WooCommerce ↔ Odoo integration.
Odoo is the master system; these tables track synchronization state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from app.database.db import Base


# ── Enums ────────────────────────────────────────────────────────────────────


class SyncStatus(str, PyEnum):
    """Synchronization status for mapping records."""

    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    SKIPPED = "skipped"


class SyncLogStatus(str, PyEnum):
    """Status for sync log entries."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class OrderStatus(str, PyEnum):
    """Order synchronization status."""

    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class FailedJobStatus(str, PyEnum):
    """Failed job resolution status."""

    PENDING = "pending"
    RETRYING = "retrying"
    RESOLVED = "resolved"
    DEAD_LETTER = "dead_letter"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


# ── Models ───────────────────────────────────────────────────────────────────


class ProductMapping(Base):
    """
    Maps Odoo product.template to WooCommerce product.

    SKU is the canonical matching key — never match by product name.
    """

    __tablename__ = "product_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    odoo_product_id = Column(Integer, nullable=False, unique=True, index=True)
    woo_product_id = Column(Integer, nullable=True, unique=True, index=True)
    sku = Column(String(255), nullable=False, unique=True, index=True)
    product_type = Column(String(50), nullable=False, default="simple")  # simple | variable
    sync_status = Column(
        Enum(SyncStatus, name="sync_status_enum"),
        nullable=False,
        default=SyncStatus.PENDING,
    )
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    variants = relationship("VariantMapping", back_populates="product", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<ProductMapping sku={self.sku!r} odoo={self.odoo_product_id} woo={self.woo_product_id}>"


class VariantMapping(Base):
    """
    Maps Odoo product.product (variant) to WooCommerce product variation.

    Each variant must have a unique SKU.
    """

    __tablename__ = "variant_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_mapping_id = Column(
        Integer,
        ForeignKey("product_mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    odoo_variant_id = Column(Integer, nullable=False, unique=True, index=True)
    woo_variant_id = Column(Integer, nullable=True, unique=True, index=True)
    sku = Column(String(255), nullable=False, unique=True, index=True)
    sync_status = Column(
        Enum(SyncStatus, name="sync_status_enum", create_type=False),
        nullable=False,
        default=SyncStatus.PENDING,
    )
    last_sync_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    product = relationship("ProductMapping", back_populates="variants")

    def __repr__(self) -> str:
        return f"<VariantMapping sku={self.sku!r} odoo={self.odoo_variant_id} woo={self.woo_variant_id}>"


class CustomerMapping(Base):
    """
    Maps WooCommerce customer to Odoo res.partner.

    Matching is done by email address — the canonical identifier.
    """

    __tablename__ = "customer_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    odoo_partner_id = Column(Integer, nullable=False, unique=True, index=True)
    woo_customer_id = Column(Integer, nullable=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def __repr__(self) -> str:
        return f"<CustomerMapping email={self.email!r} odoo={self.odoo_partner_id}>"


class OrderMapping(Base):
    """
    Maps WooCommerce order to Odoo sale.order.

    Used for idempotency — prevents duplicate order creation.
    """

    __tablename__ = "order_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    woo_order_id = Column(Integer, nullable=False, unique=True, index=True)
    odoo_order_id = Column(Integer, nullable=True, unique=True, index=True)
    order_number = Column(String(100), nullable=True, index=True)
    odoo_invoice_id = Column(Integer, nullable=True)
    status = Column(
        Enum(OrderStatus, name="order_status_enum"),
        nullable=False,
        default=OrderStatus.PENDING,
    )
    total_amount = Column(String(20), nullable=True)
    currency = Column(String(10), nullable=True, default="AUD")
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        return f"<OrderMapping woo={self.woo_order_id} odoo={self.odoo_order_id} status={self.status}>"


class SyncLog(Base):
    """
    Audit log for all synchronization events.

    Provides traceability for every sync operation.
    """

    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_logs_entity", "entity_type", "entity_id"),
        Index("ix_sync_logs_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False)  # e.g., product_create, order_sync
    entity_type = Column(String(50), nullable=False)  # e.g., product, order, customer
    entity_id = Column(String(100), nullable=True)  # SKU or ID
    direction = Column(String(20), nullable=False, default="odoo_to_woo")  # odoo_to_woo | woo_to_odoo
    status = Column(
        Enum(SyncLogStatus, name="sync_log_status_enum"),
        nullable=False,
        default=SyncLogStatus.SUCCESS,
    )
    message = Column(Text, nullable=True)
    payload = Column(JSON, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    def __repr__(self) -> str:
        return f"<SyncLog {self.event_type} {self.entity_type}:{self.entity_id} {self.status}>"


class FailedJob(Base):
    """
    Dead letter queue for failed sync operations.

    Stores failed jobs with exponential backoff retry scheduling.
    Retry sequence: 1min → 5min → 15min → 1hr → dead letter.
    """

    __tablename__ = "failed_jobs"
    __table_args__ = (
        Index("ix_failed_jobs_retry", "next_retry_at", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(100), nullable=False)  # e.g., product_sync, order_sync
    entity_type = Column(String(50), nullable=True)
    entity_id = Column(String(100), nullable=True)
    payload = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    error_traceback = Column(Text, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=4)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        Enum(FailedJobStatus, name="failed_job_status_enum"),
        nullable=False,
        default=FailedJobStatus.PENDING,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<FailedJob {self.job_type} retry={self.retry_count}/{self.max_retries} status={self.status}>"

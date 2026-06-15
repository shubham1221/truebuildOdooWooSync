"""
TrueBuild Integration Platform — Order Mapping Repository.

CRUD operations for OrderMapping records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import OrderMapping, OrderStatus
from app.utils.logging import get_logger

logger = get_logger(__name__)


class OrderMappingRepository:
    """Repository for OrderMapping CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        woo_order_id: int,
        order_number: str | None = None,
        odoo_order_id: int | None = None,
        odoo_invoice_id: int | None = None,
        total_amount: str | None = None,
        currency: str = "AUD",
        status: OrderStatus = OrderStatus.PENDING,
    ) -> OrderMapping:
        """Create a new order mapping."""
        mapping = OrderMapping(
            woo_order_id=woo_order_id,
            odoo_order_id=odoo_order_id,
            order_number=order_number,
            odoo_invoice_id=odoo_invoice_id,
            total_amount=total_amount,
            currency=currency,
            status=status,
        )
        self.db.add(mapping)
        self.db.flush()
        logger.info("order_mapping_created", woo_order_id=woo_order_id)
        return mapping

    def get_by_id(self, mapping_id: int) -> OrderMapping | None:
        """Get an order mapping by primary key."""
        return self.db.get(OrderMapping, mapping_id)

    def get_by_woo_id(self, woo_order_id: int) -> OrderMapping | None:
        """Get an order mapping by WooCommerce order ID."""
        stmt = select(OrderMapping).where(OrderMapping.woo_order_id == woo_order_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_odoo_id(self, odoo_order_id: int) -> OrderMapping | None:
        """Get an order mapping by Odoo sale order ID."""
        stmt = select(OrderMapping).where(OrderMapping.odoo_order_id == odoo_order_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_order_number(self, order_number: str) -> OrderMapping | None:
        """Get an order mapping by WooCommerce order number."""
        stmt = select(OrderMapping).where(OrderMapping.order_number == order_number)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[OrderMapping]:
        """List all order mappings with pagination."""
        stmt = (
            select(OrderMapping)
            .order_by(OrderMapping.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return self.db.execute(stmt).scalars().all()

    def list_by_status(self, status: OrderStatus) -> Sequence[OrderMapping]:
        """List all order mappings with a given status."""
        stmt = (
            select(OrderMapping)
            .where(OrderMapping.status == status)
            .order_by(OrderMapping.created_at.desc())
        )
        return self.db.execute(stmt).scalars().all()

    def update(
        self,
        mapping: OrderMapping,
        *,
        odoo_order_id: int | None = None,
        odoo_invoice_id: int | None = None,
        status: OrderStatus | None = None,
        total_amount: str | None = None,
    ) -> OrderMapping:
        """Update an order mapping."""
        if odoo_order_id is not None:
            mapping.odoo_order_id = odoo_order_id
        if odoo_invoice_id is not None:
            mapping.odoo_invoice_id = odoo_invoice_id
        if status is not None:
            mapping.status = status
        if total_amount is not None:
            mapping.total_amount = total_amount
        mapping.last_sync_at = datetime.now(timezone.utc)
        mapping.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return mapping

    def mark_synced(
        self,
        mapping: OrderMapping,
        odoo_order_id: int,
        odoo_invoice_id: int | None = None,
    ) -> OrderMapping:
        """Mark an order mapping as successfully synced."""
        return self.update(
            mapping,
            odoo_order_id=odoo_order_id,
            odoo_invoice_id=odoo_invoice_id,
            status=OrderStatus.SYNCED,
        )

    def mark_failed(self, mapping: OrderMapping) -> OrderMapping:
        """Mark an order mapping as failed."""
        return self.update(mapping, status=OrderStatus.FAILED)

    def mark_cancelled(self, mapping: OrderMapping) -> OrderMapping:
        """Mark an order mapping as cancelled."""
        return self.update(mapping, status=OrderStatus.CANCELLED)

    def mark_refunded(self, mapping: OrderMapping) -> OrderMapping:
        """Mark an order mapping as refunded."""
        return self.update(mapping, status=OrderStatus.REFUNDED)

    def delete(self, mapping: OrderMapping) -> None:
        """Delete an order mapping."""
        self.db.delete(mapping)
        self.db.flush()
        logger.info("order_mapping_deleted", woo_order_id=mapping.woo_order_id)

    def count(self) -> int:
        """Count total order mappings."""
        from sqlalchemy import func

        stmt = select(func.count(OrderMapping.id))
        return self.db.execute(stmt).scalar() or 0

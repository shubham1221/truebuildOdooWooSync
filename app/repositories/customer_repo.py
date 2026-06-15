"""
TrueBuild Integration Platform — Customer Mapping Repository.

CRUD operations for CustomerMapping records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import CustomerMapping
from app.utils.logging import get_logger

logger = get_logger(__name__)


class CustomerMappingRepository:
    """Repository for CustomerMapping CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        odoo_partner_id: int,
        email: str,
        woo_customer_id: int | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> CustomerMapping:
        """Create a new customer mapping."""
        mapping = CustomerMapping(
            odoo_partner_id=odoo_partner_id,
            woo_customer_id=woo_customer_id,
            email=email.lower().strip(),
            first_name=first_name,
            last_name=last_name,
            last_sync_at=datetime.now(timezone.utc),
        )
        self.db.add(mapping)
        self.db.flush()
        logger.info("customer_mapping_created", email=mapping.email, odoo_id=odoo_partner_id)
        return mapping

    def get_by_id(self, mapping_id: int) -> CustomerMapping | None:
        """Get a customer mapping by primary key."""
        return self.db.get(CustomerMapping, mapping_id)

    def get_by_email(self, email: str) -> CustomerMapping | None:
        """Get a customer mapping by email address."""
        stmt = select(CustomerMapping).where(CustomerMapping.email == email.lower().strip())
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_odoo_id(self, odoo_partner_id: int) -> CustomerMapping | None:
        """Get a customer mapping by Odoo partner ID."""
        stmt = select(CustomerMapping).where(CustomerMapping.odoo_partner_id == odoo_partner_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_woo_id(self, woo_customer_id: int) -> CustomerMapping | None:
        """Get a customer mapping by WooCommerce customer ID."""
        stmt = select(CustomerMapping).where(CustomerMapping.woo_customer_id == woo_customer_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[CustomerMapping]:
        """List all customer mappings with pagination."""
        stmt = select(CustomerMapping).order_by(CustomerMapping.id).limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def update(
        self,
        mapping: CustomerMapping,
        *,
        odoo_partner_id: int | None = None,
        woo_customer_id: int | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> CustomerMapping:
        """Update a customer mapping."""
        if odoo_partner_id is not None:
            mapping.odoo_partner_id = odoo_partner_id
        if woo_customer_id is not None:
            mapping.woo_customer_id = woo_customer_id
        if first_name is not None:
            mapping.first_name = first_name
        if last_name is not None:
            mapping.last_name = last_name
        mapping.last_sync_at = datetime.now(timezone.utc)
        self.db.flush()
        return mapping

    def delete(self, mapping: CustomerMapping) -> None:
        """Delete a customer mapping."""
        self.db.delete(mapping)
        self.db.flush()
        logger.info("customer_mapping_deleted", email=mapping.email)

    def count(self) -> int:
        """Count total customer mappings."""
        from sqlalchemy import func

        stmt = select(func.count(CustomerMapping.id))
        return self.db.execute(stmt).scalar() or 0

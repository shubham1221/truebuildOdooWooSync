"""
TrueBuild Integration Platform — Product Mapping Repository.

CRUD operations for ProductMapping records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ProductMapping, SyncStatus
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ProductMappingRepository:
    """Repository for ProductMapping CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        odoo_product_id: int,
        sku: str,
        woo_product_id: int | None = None,
        product_type: str = "simple",
        sync_status: SyncStatus = SyncStatus.PENDING,
    ) -> ProductMapping:
        """Create a new product mapping."""
        mapping = ProductMapping(
            odoo_product_id=odoo_product_id,
            woo_product_id=woo_product_id,
            sku=sku,
            product_type=product_type,
            sync_status=sync_status,
        )
        self.db.add(mapping)
        self.db.flush()
        logger.info("product_mapping_created", sku=sku, odoo_id=odoo_product_id)
        return mapping

    def get_by_id(self, mapping_id: int) -> ProductMapping | None:
        """Get a product mapping by primary key."""
        return self.db.get(ProductMapping, mapping_id)

    def get_by_sku(self, sku: str) -> ProductMapping | None:
        """Get a product mapping by SKU."""
        stmt = select(ProductMapping).where(ProductMapping.sku == sku)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_odoo_id(self, odoo_product_id: int) -> ProductMapping | None:
        """Get a product mapping by Odoo product template ID."""
        stmt = select(ProductMapping).where(ProductMapping.odoo_product_id == odoo_product_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_woo_id(self, woo_product_id: int) -> ProductMapping | None:
        """Get a product mapping by WooCommerce product ID."""
        stmt = select(ProductMapping).where(ProductMapping.woo_product_id == woo_product_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[ProductMapping]:
        """List all product mappings with pagination."""
        stmt = select(ProductMapping).order_by(ProductMapping.id).limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def list_by_status(self, status: SyncStatus) -> Sequence[ProductMapping]:
        """List all product mappings with a given sync status."""
        stmt = select(ProductMapping).where(ProductMapping.sync_status == status)
        return self.db.execute(stmt).scalars().all()

    def update(
        self,
        mapping: ProductMapping,
        *,
        woo_product_id: int | None = None,
        sync_status: SyncStatus | None = None,
        product_type: str | None = None,
    ) -> ProductMapping:
        """Update a product mapping."""
        if woo_product_id is not None:
            mapping.woo_product_id = woo_product_id
        if sync_status is not None:
            mapping.sync_status = sync_status
        if product_type is not None:
            mapping.product_type = product_type
        mapping.last_sync_at = datetime.now(timezone.utc)
        mapping.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return mapping

    def mark_synced(self, mapping: ProductMapping, woo_product_id: int) -> ProductMapping:
        """Mark a product mapping as successfully synced."""
        return self.update(mapping, woo_product_id=woo_product_id, sync_status=SyncStatus.SYNCED)

    def mark_failed(self, mapping: ProductMapping) -> ProductMapping:
        """Mark a product mapping as failed."""
        return self.update(mapping, sync_status=SyncStatus.FAILED)

    def delete(self, mapping: ProductMapping) -> None:
        """Delete a product mapping."""
        self.db.delete(mapping)
        self.db.flush()
        logger.info("product_mapping_deleted", sku=mapping.sku)

    def count(self) -> int:
        """Count total product mappings."""
        from sqlalchemy import func

        stmt = select(func.count(ProductMapping.id))
        return self.db.execute(stmt).scalar() or 0

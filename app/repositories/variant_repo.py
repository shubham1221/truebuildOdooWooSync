"""
TrueBuild Integration Platform — Variant Mapping Repository.

CRUD operations for VariantMapping records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import SyncStatus, VariantMapping
from app.utils.logging import get_logger

logger = get_logger(__name__)


class VariantMappingRepository:
    """Repository for VariantMapping CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        product_mapping_id: int,
        odoo_variant_id: int,
        sku: str,
        woo_variant_id: int | None = None,
        sync_status: SyncStatus = SyncStatus.PENDING,
    ) -> VariantMapping:
        """Create a new variant mapping."""
        mapping = VariantMapping(
            product_mapping_id=product_mapping_id,
            odoo_variant_id=odoo_variant_id,
            woo_variant_id=woo_variant_id,
            sku=sku,
            sync_status=sync_status,
        )
        self.db.add(mapping)
        self.db.flush()
        logger.info("variant_mapping_created", sku=sku, odoo_id=odoo_variant_id)
        return mapping

    def get_by_id(self, mapping_id: int) -> VariantMapping | None:
        """Get a variant mapping by primary key."""
        return self.db.get(VariantMapping, mapping_id)

    def get_by_sku(self, sku: str) -> VariantMapping | None:
        """Get a variant mapping by SKU."""
        stmt = select(VariantMapping).where(VariantMapping.sku == sku)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_odoo_id(self, odoo_variant_id: int) -> VariantMapping | None:
        """Get a variant mapping by Odoo product.product ID."""
        stmt = select(VariantMapping).where(VariantMapping.odoo_variant_id == odoo_variant_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_woo_id(self, woo_variant_id: int) -> VariantMapping | None:
        """Get a variant mapping by WooCommerce variation ID."""
        stmt = select(VariantMapping).where(VariantMapping.woo_variant_id == woo_variant_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_product(self, product_mapping_id: int) -> Sequence[VariantMapping]:
        """List all variant mappings for a given product."""
        stmt = (
            select(VariantMapping)
            .where(VariantMapping.product_mapping_id == product_mapping_id)
            .order_by(VariantMapping.id)
        )
        return self.db.execute(stmt).scalars().all()

    def update(
        self,
        mapping: VariantMapping,
        *,
        woo_variant_id: int | None = None,
        sync_status: SyncStatus | None = None,
    ) -> VariantMapping:
        """Update a variant mapping."""
        if woo_variant_id is not None:
            mapping.woo_variant_id = woo_variant_id
        if sync_status is not None:
            mapping.sync_status = sync_status
        mapping.last_sync_at = datetime.now(timezone.utc)
        self.db.flush()
        return mapping

    def mark_synced(self, mapping: VariantMapping, woo_variant_id: int) -> VariantMapping:
        """Mark a variant mapping as successfully synced."""
        return self.update(mapping, woo_variant_id=woo_variant_id, sync_status=SyncStatus.SYNCED)

    def mark_failed(self, mapping: VariantMapping) -> VariantMapping:
        """Mark a variant mapping as failed."""
        return self.update(mapping, sync_status=SyncStatus.FAILED)

    def delete(self, mapping: VariantMapping) -> None:
        """Delete a variant mapping."""
        self.db.delete(mapping)
        self.db.flush()
        logger.info("variant_mapping_deleted", sku=mapping.sku)

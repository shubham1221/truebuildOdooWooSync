"""
TrueBuild Integration Platform — Inventory Sync Service.

Synchronizes stock quantities from Odoo (master) to WooCommerce.
Reads stock.quant from Odoo and updates WooCommerce product/variation
stock_quantity fields.

Triggered by:
- Scheduled task (every 5 minutes)
- Manual API endpoint
- Any Odoo stock event (POS sale, purchase receipt, adjustment, transfer)
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.repositories.product_repo import ProductMappingRepository
from app.repositories.variant_repo import VariantMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.services.odoo_client import OdooClient
from app.services.woo_client import WooCommerceClient, WooCommerceAPIError
from app.utils.logging import get_logger

logger = get_logger(__name__)


class InventorySyncResult:
    """Result of an inventory sync operation."""

    def __init__(self) -> None:
        self.total_products: int = 0
        self.updated: int = 0
        self.failed: int = 0
        self.skipped: int = 0
        self.duration_seconds: float = 0.0
        self.errors: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_products": self.total_products,
            "updated": self.updated,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "errors": self.errors,
        }


class InventorySyncService:
    """
    Synchronizes inventory levels from Odoo to WooCommerce.

    For each mapped product:
    1. Read qty_available from Odoo stock.quant
    2. Update WooCommerce stock_quantity
    3. Handle both simple products and variable product variants
    """

    def __init__(
        self,
        odoo: OdooClient,
        woo: WooCommerceClient,
        db: Session,
    ) -> None:
        self.odoo = odoo
        self.woo = woo
        self.db = db
        self.settings = get_settings()
        self.product_repo = ProductMappingRepository(db)
        self.variant_repo = VariantMappingRepository(db)
        self.sync_log_repo = SyncLogRepository(db)

    def sync_all_inventory(self) -> InventorySyncResult:
        """
        Sync inventory for all mapped products.

        Reads stock quantities from Odoo and updates WooCommerce
        for every product that has a valid mapping.

        Returns:
            InventorySyncResult with counts.
        """
        start_time = time.monotonic()
        result = InventorySyncResult()
        logger.info("inventory_sync_started")

        try:
            # Get all synced product mappings
            from app.database.models import SyncStatus
            mappings = self.product_repo.list_by_status(SyncStatus.SYNCED)

            for mapping in mappings:
                result.total_products += 1
                try:
                    if mapping.product_type == "variable":
                        self._sync_variable_product_stock(mapping)
                    else:
                        self._sync_simple_product_stock(mapping)
                    result.updated += 1
                except Exception as e:
                    result.failed += 1
                    error_msg = f"Inventory sync failed for SKU {mapping.sku}: {e}"
                    result.errors.append(error_msg)
                    logger.error(
                        "inventory_sync_product_error",
                        sku=mapping.sku,
                        error=str(e),
                    )

        except Exception as e:
            logger.error("inventory_sync_error", error=str(e))
            result.errors.append(str(e))

        result.duration_seconds = round(time.monotonic() - start_time, 2)

        self.sync_log_repo.log_success(
            event_type="inventory_sync_batch",
            entity_type="inventory",
            message=(
                f"Inventory sync completed: {result.updated} updated, "
                f"{result.failed} failed out of {result.total_products}"
            ),
            duration_ms=int(result.duration_seconds * 1000),
        )

        self.db.commit()

        logger.info(
            "inventory_sync_completed",
            total=result.total_products,
            updated=result.updated,
            failed=result.failed,
            duration_seconds=result.duration_seconds,
        )

        return result

    def sync_product_inventory(self, sku: str) -> dict[str, Any]:
        """
        Sync inventory for a single product by SKU.

        Args:
            sku: Product SKU.

        Returns:
            Dict with sync result.
        """
        mapping = self.product_repo.get_by_sku(sku)
        if not mapping or not mapping.woo_product_id:
            return {
                "sku": sku,
                "status": "skipped",
                "message": "Product not found in mappings or not synced to WooCommerce",
            }

        try:
            if mapping.product_type == "variable":
                self._sync_variable_product_stock(mapping)
            else:
                self._sync_simple_product_stock(mapping)

            self.db.commit()
            return {
                "sku": sku,
                "status": "updated",
                "message": "Inventory synced successfully",
            }
        except Exception as e:
            return {
                "sku": sku,
                "status": "failed",
                "message": str(e),
            }

    def _sync_simple_product_stock(self, mapping: Any) -> None:
        """Sync stock for a simple product."""
        # Get Odoo product.product ID for this template
        variants = self.odoo.search_read(
            "product.product",
            [["product_tmpl_id", "=", mapping.odoo_product_id]],
            fields=["id", "qty_available"],
            limit=1,
        )

        if not variants:
            logger.warning(
                "no_variant_found_for_template",
                odoo_template_id=mapping.odoo_product_id,
                sku=mapping.sku,
            )
            return

        qty = int(variants[0].get("qty_available", 0))
        # Don't allow negative stock in WooCommerce
        qty = max(0, qty)

        self.woo.update_stock(mapping.woo_product_id, qty)

        logger.debug(
            "inventory_synced_simple",
            sku=mapping.sku,
            woo_product_id=mapping.woo_product_id,
            quantity=qty,
        )

    def _sync_variable_product_stock(self, mapping: Any) -> None:
        """Sync stock for all variants of a variable product."""
        variant_mappings = self.variant_repo.list_by_product(mapping.id)

        if not variant_mappings:
            logger.warning(
                "no_variant_mappings",
                sku=mapping.sku,
                product_mapping_id=mapping.id,
            )
            return

        for vm in variant_mappings:
            if not vm.woo_variant_id:
                continue

            try:
                # Get stock from Odoo for this specific variant
                variant_data = self.odoo.search_read(
                    "product.product",
                    [["id", "=", vm.odoo_variant_id]],
                    fields=["qty_available"],
                    limit=1,
                )

                if variant_data:
                    qty = int(variant_data[0].get("qty_available", 0))
                    qty = max(0, qty)

                    self.woo.update_variation_stock(
                        mapping.woo_product_id,
                        vm.woo_variant_id,
                        qty,
                    )

                    logger.debug(
                        "inventory_synced_variant",
                        sku=vm.sku,
                        woo_product_id=mapping.woo_product_id,
                        woo_variant_id=vm.woo_variant_id,
                        quantity=qty,
                    )

            except WooCommerceAPIError as e:
                logger.error(
                    "variant_stock_update_error",
                    sku=vm.sku,
                    woo_variant_id=vm.woo_variant_id,
                    error=str(e),
                )
                raise

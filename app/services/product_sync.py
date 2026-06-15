"""
TrueBuild Integration Platform — Product Sync Service.

Orchestrates product synchronization from Odoo (master) to WooCommerce (channel).
Products are matched by SKU — never by name.
Products without SKU are rejected with an error log.

Handles: simple products, variable products, categories, images, GST tax class.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.models import SyncStatus
from app.repositories.product_repo import ProductMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.repositories.failed_job_repo import FailedJobRepository
from app.schemas.product import ProductSyncResult, ProductSyncSummary
from app.services.odoo_client import OdooClient, OdooAPIError
from app.services.woo_client import WooCommerceClient, WooCommerceAPIError
from app.services.variant_sync import VariantSyncService
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ProductSyncService:
    """
    Orchestrates full product synchronization from Odoo to WooCommerce.

    Flow for each product:
    1. Read product.template from Odoo
    2. Validate SKU exists (reject if missing)
    3. Check ProductMapping by SKU
    4. Determine if simple or variable product
    5. Sync category (create in WooCommerce if missing)
    6. Create or update WooCommerce product
    7. If variable: sync all variants
    8. Update mapping records
    9. Write audit log
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
        self.sync_log_repo = SyncLogRepository(db)
        self.failed_job_repo = FailedJobRepository(db)
        self.variant_sync = VariantSyncService(odoo, woo, db)

        # Cache for WooCommerce categories to avoid repeated lookups
        self._category_cache: dict[str, int] = {}

    # ── Full Sync ────────────────────────────────────────────────────────

    def sync_all_products(self) -> ProductSyncSummary:
        """
        Sync all active products from Odoo to WooCommerce.

        Returns:
            Summary with counts of created, updated, skipped, failed products.
        """
        start_time = time.monotonic()
        summary = ProductSyncSummary()

        logger.info("product_sync_all_started")

        try:
            # Fetch all storable/consumable products from Odoo
            offset = 0
            batch_size = self.settings.SYNC_BATCH_SIZE

            while True:
                odoo_products = self.odoo.get_product_templates(
                    limit=batch_size, offset=offset
                )
                if not odoo_products:
                    break

                for product in odoo_products:
                    result = self._sync_single_product(product)
                    summary.results.append(result)

                    if result.action == "created":
                        summary.created += 1
                    elif result.action == "updated":
                        summary.updated += 1
                    elif result.action == "skipped":
                        summary.skipped += 1
                    elif result.action == "failed":
                        summary.failed += 1

                    summary.total_products += 1

                offset += batch_size
                if len(odoo_products) < batch_size:
                    break

        except Exception as e:
            logger.error("product_sync_all_error", error=str(e))
            summary.errors.append(str(e))

        summary.duration_seconds = round(time.monotonic() - start_time, 2)

        logger.info(
            "product_sync_all_completed",
            total=summary.total_products,
            created=summary.created,
            updated=summary.updated,
            skipped=summary.skipped,
            failed=summary.failed,
            duration_seconds=summary.duration_seconds,
        )

        # Commit all changes
        self.db.commit()
        return summary

    def sync_product_by_sku(self, sku: str) -> ProductSyncResult:
        """
        Sync a single product by SKU.

        Args:
            sku: The product's internal reference (SKU) in Odoo.

        Returns:
            Sync result for the product.
        """
        logger.info("product_sync_single_started", sku=sku)

        # Find the product in Odoo by SKU
        odoo_products = self.odoo.search_read(
            "product.template",
            [["default_code", "=", sku]],
            fields=[
                "name", "default_code", "description", "description_sale",
                "list_price", "standard_price", "categ_id", "image_1920",
                "barcode", "type", "active", "attribute_line_ids",
                "product_variant_ids", "product_variant_count", "weight",
                "taxes_id",
            ],
            limit=1,
        )

        if not odoo_products:
            logger.warning("product_not_found_in_odoo", sku=sku)
            return ProductSyncResult(
                sku=sku,
                odoo_product_id=0,
                action="failed",
                message=f"Product with SKU '{sku}' not found in Odoo",
            )

        result = self._sync_single_product(odoo_products[0])
        self.db.commit()
        return result

    # ── Internal Sync Logic ──────────────────────────────────────────────

    def _sync_single_product(self, odoo_product: dict[str, Any]) -> ProductSyncResult:
        """
        Sync a single product from Odoo data to WooCommerce.

        Args:
            odoo_product: Product data from Odoo search_read.

        Returns:
            ProductSyncResult with action and status.
        """
        start_time = time.monotonic()
        odoo_id = odoo_product["id"]
        sku = odoo_product.get("default_code", "")
        name = odoo_product.get("name", "")

        # ── Validate SKU ─────────────────────────────────────────────
        if not sku:
            logger.error(
                "product_sync_skipped_no_sku",
                odoo_id=odoo_id,
                product_name=name,
            )
            self.sync_log_repo.log_failure(
                event_type="product_sync",
                entity_type="product",
                entity_id=str(odoo_id),
                message=f"Product '{name}' (ID: {odoo_id}) has no SKU — rejected",
            )
            return ProductSyncResult(
                sku="",
                odoo_product_id=odoo_id,
                action="skipped",
                message=f"No SKU for product '{name}' (Odoo ID: {odoo_id})",
            )

        try:
            # ── Determine product type ───────────────────────────────
            variant_count = odoo_product.get("product_variant_count", 1)
            is_variable = variant_count > 1
            product_type = "variable" if is_variable else "simple"

            # ── Build WooCommerce data ───────────────────────────────
            woo_data = self._build_woo_product_data(odoo_product, product_type)

            # ── Handle category ──────────────────────────────────────
            category_name = self._get_category_name(odoo_product)
            if category_name:
                woo_cat_id = self._ensure_woo_category(category_name)
                if woo_cat_id:
                    woo_data["categories"] = [{"id": woo_cat_id}]

            # ── Check existing mapping ───────────────────────────────
            existing_mapping = self.product_repo.get_by_sku(sku)

            if existing_mapping and existing_mapping.woo_product_id:
                # UPDATE existing WooCommerce product
                self.woo.update_product(existing_mapping.woo_product_id, woo_data)
                woo_product_id = existing_mapping.woo_product_id
                self.product_repo.update(
                    existing_mapping,
                    sync_status=SyncStatus.SYNCED,
                    product_type=product_type,
                )
                action = "updated"
            else:
                # CREATE new WooCommerce product
                woo_result = self.woo.create_product(woo_data)
                woo_product_id = woo_result["id"]

                if existing_mapping:
                    self.product_repo.mark_synced(existing_mapping, woo_product_id)
                    existing_mapping.product_type = product_type
                else:
                    self.product_repo.create(
                        odoo_product_id=odoo_id,
                        sku=sku,
                        woo_product_id=woo_product_id,
                        product_type=product_type,
                        sync_status=SyncStatus.SYNCED,
                    )
                action = "created"

            # ── Sync variants if variable product ────────────────────
            variants_synced = 0
            variants_failed = 0
            if is_variable:
                mapping = self.product_repo.get_by_sku(sku)
                variant_counts = self.variant_sync.sync_variants(
                    odoo_template_id=odoo_id,
                    woo_product_id=woo_product_id,
                    product_mapping_id=mapping.id if mapping else 0,
                    attributes=woo_data.get("attributes", []),
                )
                variants_synced = variant_counts.get("synced", 0)
                variants_failed = variant_counts.get("failed", 0)

            # ── Audit log ────────────────────────────────────────────
            duration_ms = int((time.monotonic() - start_time) * 1000)
            self.sync_log_repo.log_success(
                event_type=f"product_{action}",
                entity_type="product",
                entity_id=sku,
                message=f"Product '{name}' {action} in WooCommerce (ID: {woo_product_id})",
                duration_ms=duration_ms,
            )

            logger.info(
                f"product_{action}",
                sku=sku,
                odoo_id=odoo_id,
                woo_id=woo_product_id,
                product_type=product_type,
                variants_synced=variants_synced,
                duration_ms=duration_ms,
            )

            return ProductSyncResult(
                sku=sku,
                odoo_product_id=odoo_id,
                woo_product_id=woo_product_id,
                action=action,
                message=f"Product '{name}' {action} successfully",
                variants_synced=variants_synced,
                variants_failed=variants_failed,
            )

        except (OdooAPIError, WooCommerceAPIError) as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.error(
                "product_sync_failed",
                sku=sku,
                odoo_id=odoo_id,
                error=str(e),
                duration_ms=duration_ms,
            )
            self.sync_log_repo.log_failure(
                event_type="product_sync",
                entity_type="product",
                entity_id=sku,
                message=str(e),
                duration_ms=duration_ms,
            )

            # Create failed job for retry
            self.failed_job_repo.create(
                job_type="product_sync",
                entity_type="product",
                entity_id=sku,
                payload={"sku": sku, "odoo_id": odoo_id},
                error_message=str(e),
                max_retries=self.settings.MAX_RETRIES,
                retry_delays=self.settings.RETRY_DELAYS_SECONDS,
            )

            # Mark mapping as failed if it exists
            mapping = self.product_repo.get_by_sku(sku)
            if mapping:
                self.product_repo.mark_failed(mapping)

            return ProductSyncResult(
                sku=sku,
                odoo_product_id=odoo_id,
                action="failed",
                message=str(e),
            )

        except Exception as e:
            logger.error(
                "product_sync_unexpected_error",
                sku=sku,
                odoo_id=odoo_id,
                error=str(e),
                exc_info=True,
            )
            self.sync_log_repo.log_failure(
                event_type="product_sync",
                entity_type="product",
                entity_id=sku,
                message=f"Unexpected error: {e}",
            )
            return ProductSyncResult(
                sku=sku,
                odoo_product_id=odoo_id,
                action="failed",
                message=f"Unexpected error: {e}",
            )

    def _build_woo_product_data(
        self,
        odoo_product: dict[str, Any],
        product_type: str,
    ) -> dict[str, Any]:
        """Build WooCommerce product data dict from Odoo product."""
        data: dict[str, Any] = {
            "name": odoo_product.get("name", ""),
            "type": product_type,
            "sku": odoo_product.get("default_code", ""),
            "regular_price": str(odoo_product.get("list_price", 0.0)),
            "description": odoo_product.get("description") or "",
            "short_description": odoo_product.get("description_sale") or "",
            "manage_stock": True,
            "tax_class": self.settings.GST_TAX_CLASS,
            "status": "publish",
        }

        # Stock quantity (for simple products)
        if product_type == "simple":
            # Get stock from variant (simple products have 1 variant)
            variant_ids = odoo_product.get("product_variant_ids", [])
            if variant_ids:
                variants = self.odoo.search_read(
                    "product.product",
                    [["id", "in", variant_ids]],
                    fields=["qty_available"],
                    limit=1,
                )
                if variants:
                    data["stock_quantity"] = int(variants[0].get("qty_available", 0))

        # Weight
        weight = odoo_product.get("weight")
        if weight:
            data["weight"] = str(weight)

        # Barcode as meta_data
        barcode = odoo_product.get("barcode")
        if barcode:
            data["meta_data"] = [
                {"key": "barcode", "value": barcode},
            ]

        # Image and Gallery Images (Odoo template image + product.image gallery)
        image_data = odoo_product.get("image_1920")
        images_list = []
        odoo_id = odoo_product["id"]

        if image_data:
            image_url = f"{self.odoo.url}/web/image/product.template/{odoo_id}/image_1920"
            images_list.append({"src": image_url, "name": data["name"]})

        # Fetch additional gallery images from Odoo's product.image model
        try:
            extra_images = self.odoo.search_read(
                "product.image",
                [["product_tmpl_id", "=", odoo_id]],
                fields=["id", "name"],
                limit=10,
            )
            for img in extra_images:
                img_id = img["id"]
                img_name = img.get("name") or f"{data['name']} Extra"
                img_url = f"{self.odoo.url}/web/image/product.image/{img_id}/image_1920"
                images_list.append({"src": img_url, "name": img_name})
        except Exception as e:
            logger.warning(
                "failed_fetching_odoo_gallery_images",
                odoo_id=odoo_id,
                error=str(e),
            )

        if images_list:
            data["images"] = images_list

        # Attributes (for variable products)
        if product_type == "variable":
            attributes = self.variant_sync.build_woo_attributes_from_odoo(odoo_product)
            if attributes:
                data["attributes"] = attributes

        return data

    def _get_category_name(self, odoo_product: dict[str, Any]) -> str:
        """Extract category name from Odoo product data."""
        categ_id = odoo_product.get("categ_id")
        if isinstance(categ_id, (list, tuple)) and len(categ_id) > 1:
            return categ_id[1]
        return ""

    def _ensure_woo_category(self, category_name: str) -> int | None:
        """
        Ensure a WooCommerce category exists, creating it if needed.

        Uses an in-memory cache to avoid repeated API calls.

        Returns:
            WooCommerce category ID, or None if creation fails.
        """
        if not category_name:
            return None

        # Check cache first
        if category_name in self._category_cache:
            return self._category_cache[category_name]

        try:
            # Search WooCommerce for existing category
            existing = self.woo.find_category_by_name(category_name)
            if existing:
                cat_id = existing["id"]
                self._category_cache[category_name] = cat_id
                return cat_id

            # Create new category
            result = self.woo.create_category({"name": category_name})
            cat_id = result["id"]
            self._category_cache[category_name] = cat_id
            logger.info("woo_category_ensured", name=category_name, woo_id=cat_id)
            return cat_id

        except WooCommerceAPIError as e:
            logger.warning(
                "woo_category_error",
                category=category_name,
                error=str(e),
            )
            return None

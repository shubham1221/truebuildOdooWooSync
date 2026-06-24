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



class OdooPricelistHelper:
    """
    Helper to fetch and calculate pricing using Odoo's pricelists.
    Fetches and caches all fixed/discount rules of a specific pricelist to
    allow rapid O(1) price resolution during product sync runs.
    """

    def __init__(self, odoo_client: OdooClient, pricelist_id: int) -> None:
        self.odoo = odoo_client
        self.pricelist_id = pricelist_id
        self.variant_rules: dict[int, dict[str, Any]] = {}
        self.template_rules: dict[int, dict[str, Any]] = {}
        self.category_rules: dict[int, dict[str, Any]] = {}
        self.global_rule: dict[str, Any] | None = None
        self.is_loaded = False

    def load(self) -> None:
        """Fetch all items from the configured Odoo pricelist."""
        if self.is_loaded:
            return

        try:
            logger.info("loading_odoo_pricelist_items", pricelist_id=self.pricelist_id)
            items = self.odoo.search_read(
                "product.pricelist.item",
                [["pricelist_id", "=", self.pricelist_id]],
                fields=[
                    "id",
                    "applied_on",
                    "product_tmpl_id",
                    "product_id",
                    "categ_id",
                    "compute_price",
                    "fixed_price",
                    "percent_price",
                    "price_discount",
                    "price_surcharge",
                    "base",
                ],
                limit=10000,
            )

            for item in items:
                applied_on = item.get("applied_on")
                if applied_on == "0_product_variant":
                    pid = item.get("product_id")
                    if pid and isinstance(pid, (list, tuple)) and len(pid) > 0:
                        self.variant_rules[pid[0]] = item
                elif applied_on == "1_product":
                    tmpl_id = item.get("product_tmpl_id")
                    if tmpl_id and isinstance(tmpl_id, (list, tuple)) and len(tmpl_id) > 0:
                        self.template_rules[tmpl_id[0]] = item
                elif applied_on == "2_product_category":
                    cat_id = item.get("categ_id")
                    if cat_id and isinstance(cat_id, (list, tuple)) and len(cat_id) > 0:
                        self.category_rules[cat_id[0]] = item
                elif applied_on == "3_global":
                    self.global_rule = item

            self.is_loaded = True
            logger.info(
                "odoo_pricelist_items_loaded",
                pricelist_id=self.pricelist_id,
                variant_rules_count=len(self.variant_rules),
                template_rules_count=len(self.template_rules),
                category_rules_count=len(self.category_rules),
                has_global_rule=self.global_rule is not None,
            )
        except Exception as e:
            logger.error(
                "failed_loading_pricelist_items",
                pricelist_id=self.pricelist_id,
                error=str(e),
            )
            # Keep is_loaded False so it falls back to standard base price

    def get_price(
        self,
        product_tmpl_id: int,
        product_id: int | None,
        base_price: float,
        category_id: int | None = None,
    ) -> float:
        """
        Resolve the pricelist price for a given template and variant.
        Falls back to base_price if no rules apply or loading failed.
        """
        if not self.is_loaded:
            return base_price

        # 1. Match specific variant rule
        if product_id is not None and product_id in self.variant_rules:
            return self._calculate_item_price(self.variant_rules[product_id], base_price)

        # 2. Match template rule
        if product_tmpl_id in self.template_rules:
            return self._calculate_item_price(self.template_rules[product_tmpl_id], base_price)

        # 3. Match category rule
        if category_id is not None and category_id in self.category_rules:
            return self._calculate_item_price(self.category_rules[category_id], base_price)

        # 4. Match global rule
        if self.global_rule is not None:
            return self._calculate_item_price(self.global_rule, base_price)

        return base_price

    def _calculate_item_price(self, item: dict[str, Any], base_price: float) -> float:
        compute_price = item.get("compute_price", "fixed")
        if compute_price == "fixed":
            return float(item.get("fixed_price", 0.0))
        elif compute_price == "percentage":
            percent = float(item.get("percent_price", 0.0))
            return base_price * (1.0 - percent / 100.0)
        elif compute_price == "formula":
            discount = float(item.get("price_discount", 0.0))
            surcharge = float(item.get("price_surcharge", 0.0))
            return base_price * (1.0 - discount / 100.0) + surcharge
        return base_price


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
        self.pricelist_helper = OdooPricelistHelper(self.odoo, self.settings.ODOO_PRICELIST_ID)
        self.product_repo = ProductMappingRepository(db)
        self.sync_log_repo = SyncLogRepository(db)
        self.failed_job_repo = FailedJobRepository(db)
        self.variant_sync = VariantSyncService(odoo, woo, db, pricelist_helper=self.pricelist_helper)

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
            # Load pricelist rules before starting full sync
            self.pricelist_helper.load()

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

        # Load pricelist rules before single product sync
        self.pricelist_helper.load()

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

        # If SKU is empty but has variants, derive parent SKU from variants
        if not sku and odoo_product.get("product_variant_count", 1) > 1:
            try:
                odoo_variants = self.odoo.get_product_variants(odoo_id)
                if odoo_variants:
                    sku = self._get_parent_sku_from_variants(odoo_variants)
                    if sku:
                        logger.info(
                            "derived_parent_sku_from_variants",
                            odoo_id=odoo_id,
                            derived_sku=sku,
                            message=f"Derived parent SKU '{sku}' from variants for product '{name}'"
                        )
            except Exception as e:
                logger.warning(
                    "failed_deriving_parent_sku",
                    odoo_id=odoo_id,
                    error=str(e)
                )

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
            woo_data = self._build_woo_product_data(odoo_product, product_type, sku)

            # ── Handle category ──────────────────────────────────────
            category_name = self._get_category_name(odoo_product)
            if category_name:
                woo_cat_id = self._ensure_woo_category(category_name)
                if woo_cat_id:
                    woo_data["categories"] = [{"id": woo_cat_id}]

            # ── Check existing mapping by Odoo ID or SKU ─────────────
            existing_mapping = self.product_repo.get_by_odoo_id(odoo_id)
            if not existing_mapping:
                existing_mapping = self.product_repo.get_by_sku(sku)

            if existing_mapping:
                # Ensure the mapping has the correct SKU and Odoo ID
                if existing_mapping.sku != sku:
                    existing_mapping.sku = sku
                if existing_mapping.odoo_product_id != odoo_id:
                    existing_mapping.odoo_product_id = odoo_id

            woo_product_id = None
            action = None

            if existing_mapping and existing_mapping.woo_product_id:
                # UPDATE existing WooCommerce product
                try:
                    self.woo.update_product(existing_mapping.woo_product_id, woo_data)
                    woo_product_id = existing_mapping.woo_product_id
                    self.product_repo.update(
                        existing_mapping,
                        sync_status=SyncStatus.SYNCED,
                        product_type=product_type,
                    )
                    action = "updated"
                except WooCommerceAPIError as e:
                    if e.status_code in (400, 404) and ("Invalid ID" in str(e) or "not found" in str(e).lower()):
                        logger.warning(
                            "woo_product_not_found_on_update",
                            woo_id=existing_mapping.woo_product_id,
                            sku=sku,
                            message="WooCommerce product deleted or not found — clearing mapping and creating new"
                        )
                        self.product_repo.delete(existing_mapping)
                        existing_mapping = None
                    else:
                        raise

            if not existing_mapping or not woo_product_id:
                # No local mapping (or invalid mapping) — check WooCommerce by SKU before creating
                existing_woo_product = self.woo.get_product_by_sku(sku)

                if existing_woo_product:
                    # Product already exists in WooCommerce with this SKU — update it
                    woo_product_id = existing_woo_product["id"]
                    self.woo.update_product(woo_product_id, woo_data)

                    logger.info(
                        "product_found_in_woo_by_sku",
                        sku=sku,
                        woo_id=woo_product_id,
                        message="Product matched by SKU in WooCommerce — updating instead of creating",
                    )

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
                    action = "updated"
                else:
                    # No product with this SKU in WooCommerce — create new
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
        sku: str,
    ) -> dict[str, Any]:
        """Build WooCommerce product data dict from Odoo product."""
        # Resolve pricelist price for templates and simple products
        base_price = float(odoo_product.get("list_price", 0.0))
        tmpl_id = odoo_product["id"]

        # Get category ID if available
        categ_id_val = odoo_product.get("categ_id")
        category_id = None
        if isinstance(categ_id_val, (list, tuple)) and len(categ_id_val) > 0:
            category_id = categ_id_val[0]

        # Get variant ID if simple product
        variant_id = None
        variant_ids = odoo_product.get("product_variant_ids", [])
        if variant_ids and isinstance(variant_ids, list) and len(variant_ids) > 0:
            variant_id = variant_ids[0]

        price = self.pricelist_helper.get_price(tmpl_id, variant_id, base_price, category_id)

        data: dict[str, Any] = {
            "name": odoo_product.get("name", ""),
            "type": product_type,
            "sku": sku,
            "regular_price": str(price),
            "description": odoo_product.get("description") or "",
            "short_description": odoo_product.get("description_sale") or "",
            "manage_stock": False if product_type == "variable" else True,
            "tax_class": self.settings.GST_TAX_CLASS,
            "status": "publish",
        }
        if product_type == "variable":
            data["stock_status"] = "instock"

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

        # Meta data (Barcode & Cost)
        meta_data = []
        barcode = odoo_product.get("barcode")
        if barcode:
            meta_data.append({"key": "barcode", "value": barcode})
            
        cost = odoo_product.get("standard_price")
        if cost is not None:
            meta_data.append({"key": "_wc_cog_cost", "value": str(cost)})
            
        if meta_data:
            data["meta_data"] = meta_data

        # Image and Gallery Images (Odoo template image + product.image gallery)
        image_data = odoo_product.get("image_1920")
        images_list = []
        odoo_id = odoo_product["id"]

        if image_data:
            image_url = f"{self.odoo.url}/web/image/product.template/{odoo_id}/image_1920/image.jpg"
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
                img_url = f"{self.odoo.url}/web/image/product.image/{img_id}/image_1920/image.jpg"
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

    def _get_parent_sku_from_variants(self, odoo_variants: list[dict[str, Any]]) -> str:
        """
        Derive a parent SKU from the SKUs of its child variants.
        Finds the common prefix of variant SKUs, or splits the first SKU.
        """
        skus = [v.get("default_code") for v in odoo_variants if v.get("default_code")]
        if not skus:
            return ""
        import os
        common = os.path.commonprefix(skus)
        common = common.rstrip("-_")
        if len(common) < 3:
            first_sku = skus[0]
            if "-" in first_sku:
                common = first_sku.rsplit("-", 1)[0]
            else:
                common = first_sku
        return common

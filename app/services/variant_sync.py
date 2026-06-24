"""
TrueBuild Integration Platform — Variant Sync Service.

Handles synchronization of product variants (product.product) from Odoo
to WooCommerce variations. Each variant must have a unique SKU.

Supports any attribute types: Color, Size, Thickness, Design, Length, Width, etc.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import SyncStatus
from app.repositories.variant_repo import VariantMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.schemas.product import ProductVariantData
from app.services.odoo_client import OdooClient
from app.services.woo_client import WooCommerceClient
from app.utils.logging import get_logger

logger = get_logger(__name__)


class VariantSyncService:
    """
    Synchronizes Odoo product variants to WooCommerce variations.

    Each Odoo product.product variant maps to a WooCommerce variation
    within a variable product. Variants are matched by SKU.
    """

    def __init__(
        self,
        odoo: OdooClient,
        woo: WooCommerceClient,
        db: Session,
        pricelist_helper: Any | None = None,
    ) -> None:
        self.odoo = odoo
        self.woo = woo
        self.db = db
        self.pricelist_helper = pricelist_helper
        self.variant_repo = VariantMappingRepository(db)
        self.sync_log_repo = SyncLogRepository(db)

    def sync_variants(
        self,
        odoo_template_id: int,
        woo_product_id: int,
        product_mapping_id: int,
        attributes: list[dict[str, Any]],
    ) -> dict[str, int]:
        """
        Sync all variants for a product template.

        Args:
            odoo_template_id: Odoo product.template ID
            woo_product_id: WooCommerce product ID
            product_mapping_id: ProductMapping ID for FK relationship
            attributes: List of WooCommerce attribute definitions

        Returns:
            Dict with counts: synced, failed, skipped
        """
        start_time = time.monotonic()
        counts = {"synced": 0, "failed": 0, "skipped": 0}

        try:
            # Fetch all variants from Odoo
            odoo_variants = self.odoo.get_product_variants(odoo_template_id)
            logger.info(
                "variant_sync_started",
                odoo_template_id=odoo_template_id,
                variant_count=len(odoo_variants),
            )

            for variant_data in odoo_variants:
                try:
                    result = self._sync_single_variant(
                        variant_data=variant_data,
                        woo_product_id=woo_product_id,
                        product_mapping_id=product_mapping_id,
                        odoo_template_id=odoo_template_id,
                    )
                    if result == "synced":
                        counts["synced"] += 1
                    elif result == "skipped":
                        counts["skipped"] += 1
                except Exception as e:
                    counts["failed"] += 1
                    sku = variant_data.get("default_code", "")
                    logger.error(
                        "variant_sync_error",
                        odoo_variant_id=variant_data.get("id"),
                        sku=sku,
                        error=str(e),
                    )
                    self.sync_log_repo.log_failure(
                        event_type="variant_sync",
                        entity_type="variant",
                        entity_id=sku,
                        message=str(e),
                    )

            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.info(
                "variant_sync_completed",
                odoo_template_id=odoo_template_id,
                duration_ms=duration_ms,
                **counts,
            )
            return counts

        except Exception as e:
            logger.error(
                "variant_sync_batch_error",
                odoo_template_id=odoo_template_id,
                error=str(e),
            )
            raise

    def _sync_single_variant(
        self,
        variant_data: dict[str, Any],
        woo_product_id: int,
        product_mapping_id: int,
        odoo_template_id: int | None = None,
    ) -> str:
        """
        Sync a single variant to WooCommerce.

        Returns: "synced" or "skipped"
        """
        odoo_variant_id = variant_data["id"]
        sku = variant_data.get("default_code", "")

        # SKU is mandatory for variant sync
        if not sku:
            logger.warning(
                "variant_skipped_no_sku",
                odoo_variant_id=odoo_variant_id,
                product_name=variant_data.get("name", ""),
            )
            self.sync_log_repo.log_failure(
                event_type="variant_sync",
                entity_type="variant",
                entity_id=str(odoo_variant_id),
                message=f"Variant {odoo_variant_id} has no SKU — skipped",
            )
            return "skipped"

        # Build variant attribute values
        attribute_values = self._build_attribute_values(variant_data)

        # Resolve pricelist price for variant
        base_price = float(variant_data.get("lst_price", 0.0))
        tmpl_id = None
        tmpl_val = variant_data.get("product_tmpl_id")
        if isinstance(tmpl_val, (list, tuple)) and len(tmpl_val) > 0:
            tmpl_id = tmpl_val[0]
        if not tmpl_id:
            tmpl_id = odoo_template_id

        categ_id_val = variant_data.get("categ_id")
        category_id = None
        if isinstance(categ_id_val, (list, tuple)) and len(categ_id_val) > 0:
            category_id = categ_id_val[0]

        if self.pricelist_helper and tmpl_id:
            price = self.pricelist_helper.get_price(tmpl_id, odoo_variant_id, base_price, category_id)
        else:
            price = base_price

        # Build WooCommerce variation data
        woo_variation_data: dict[str, Any] = {
            "sku": sku,
            "regular_price": str(price),
            "manage_stock": True,
            "stock_quantity": int(variant_data.get("qty_available", 0)),
            "attributes": attribute_values,
        }

        # Add cost (standard_price) as meta_data for variations
        cost = variant_data.get("standard_price")
        if cost is not None:
            woo_variation_data["meta_data"] = [
                {"key": "_wc_cog_cost", "value": str(cost)}
            ]

        # Add weight if available
        weight = variant_data.get("weight")
        if weight:
            woo_variation_data["weight"] = str(weight)

        # Check existing mapping (by Odoo ID, which maps to SKU)
        existing = self.variant_repo.get_by_odoo_id(odoo_variant_id)

        # Also check by SKU in case mapping is missing but variant exists
        if not existing:
            existing = self.variant_repo.get_by_sku(sku)

        if existing and existing.woo_variant_id:
            # Update existing variation (matched by SKU mapping)
            self.woo.update_variation(
                woo_product_id, existing.woo_variant_id, woo_variation_data
            )
            self.variant_repo.update(
                existing,
                sync_status=SyncStatus.SYNCED,
            )
            logger.info(
                "variant_updated",
                sku=sku,
                woo_variation_id=existing.woo_variant_id,
            )
        else:
            # No local mapping — check WooCommerce variations by SKU
            # to prevent duplicates and ensure SKU-only matching
            existing_woo_variation = self._find_woo_variation_by_sku(
                woo_product_id, sku
            )

            if existing_woo_variation:
                # Variation with this SKU already exists in WooCommerce — update it
                woo_variant_id = existing_woo_variation["id"]
                self.woo.update_variation(
                    woo_product_id, woo_variant_id, woo_variation_data
                )

                logger.info(
                    "variant_found_in_woo_by_sku",
                    sku=sku,
                    woo_variation_id=woo_variant_id,
                    message="Variation matched by SKU in WooCommerce — updating instead of creating",
                )

                if existing:
                    self.variant_repo.mark_synced(existing, woo_variant_id)
                else:
                    self.variant_repo.create(
                        product_mapping_id=product_mapping_id,
                        odoo_variant_id=odoo_variant_id,
                        sku=sku,
                        woo_variant_id=woo_variant_id,
                        sync_status=SyncStatus.SYNCED,
                    )
            else:
                # No variation with this SKU in WooCommerce — create new
                woo_variation = self.woo.create_variation(woo_product_id, woo_variation_data)
                woo_variant_id = woo_variation["id"]

                if existing:
                    self.variant_repo.mark_synced(existing, woo_variant_id)
                else:
                    self.variant_repo.create(
                        product_mapping_id=product_mapping_id,
                        odoo_variant_id=odoo_variant_id,
                        sku=sku,
                        woo_variant_id=woo_variant_id,
                        sync_status=SyncStatus.SYNCED,
                    )
                logger.info(
                    "variant_created",
                    sku=sku,
                    woo_variation_id=woo_variant_id,
                )

        self.sync_log_repo.log_success(
            event_type="variant_sync",
            entity_type="variant",
            entity_id=sku,
            message=f"Variant synced: {sku}",
        )
        return "synced"

    def _find_woo_variation_by_sku(
        self,
        woo_product_id: int,
        sku: str,
    ) -> dict[str, Any] | None:
        """
        Find an existing WooCommerce variation by SKU within a product.

        Iterates through all variations of the product to find one matching
        the given SKU. Returns the variation dict if found, else None.
        """
        try:
            variations = self.woo.list_variations(woo_product_id)
            for variation in variations:
                if variation.get("sku") == sku:
                    return variation
        except Exception as e:
            logger.warning(
                "woo_variation_sku_lookup_error",
                woo_product_id=woo_product_id,
                sku=sku,
                error=str(e),
            )
        return None

    def _build_attribute_values(
        self,
        variant_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        """
        Build WooCommerce attribute values for a variant.

        Reads product_template_attribute_value_ids from the variant
        and resolves them to attribute name/value pairs.
        """
        attr_value_ids = variant_data.get("product_template_attribute_value_ids", [])
        if not attr_value_ids:
            return []

        # Fetch attribute value details from Odoo
        attr_values = self.odoo.get_attribute_values(attr_value_ids)

        result = []
        for av in attr_values:
            attr_name = ""
            if av.get("attribute_id"):
                # attribute_id is a tuple: (id, name)
                if isinstance(av["attribute_id"], (list, tuple)) and len(av["attribute_id"]) > 1:
                    attr_name = av["attribute_id"][1]
                else:
                    attr_name = str(av["attribute_id"])

            value_name = av.get("name", "")
            if attr_name and value_name:
                result.append({
                    "name": attr_name,
                    "option": value_name,
                })

        return result

    def build_woo_attributes_from_odoo(
        self,
        odoo_template: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build WooCommerce product attribute definitions from Odoo template.

        Reads attribute_line_ids from the product template and constructs
        the attributes array for WooCommerce variable product creation.

        Returns:
            List of WooCommerce attribute definitions.
        """
        attr_line_ids = odoo_template.get("attribute_line_ids", [])
        if not attr_line_ids:
            return []

        # Fetch attribute lines from Odoo
        attr_lines = self.odoo.search_read(
            "product.template.attribute.line",
            [["id", "in", attr_line_ids]],
            fields=["attribute_id", "value_ids"],
        )

        woo_attributes = []
        for position, line in enumerate(attr_lines):
            attr_id = line.get("attribute_id")
            attr_name = ""
            if isinstance(attr_id, (list, tuple)) and len(attr_id) > 1:
                attr_name = attr_id[1]
            elif attr_id:
                # Fetch attribute name
                attrs = self.odoo.read("product.attribute", [attr_id], ["name"])
                if attrs:
                    attr_name = attrs[0].get("name", "")

            # Fetch value names
            value_ids = line.get("value_ids", [])
            if value_ids:
                values = self.odoo.search_read(
                    "product.attribute.value",
                    [["id", "in", value_ids]],
                    fields=["name"],
                )
                value_names = [v["name"] for v in values if v.get("name")]
            else:
                value_names = []

            if attr_name and value_names:
                woo_attributes.append({
                    "name": attr_name,
                    "position": position,
                    "visible": True,
                    "variation": True,
                    "options": value_names,
                })

        return woo_attributes

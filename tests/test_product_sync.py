"""
TrueBuild — Product Sync Unit Tests.

Tests the product synchronization service with mocked Odoo and WooCommerce.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.database.models import ProductMapping, SyncStatus
from app.repositories.product_repo import ProductMappingRepository
from app.services.product_sync import ProductSyncService


class TestProductSync:
    """Tests for ProductSyncService."""

    def test_sync_product_no_sku_skipped(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Products without SKU should be skipped."""
        service = ProductSyncService(mock_odoo, mock_woo, db_session)
        product = {
            "id": 100,
            "name": "No SKU Product",
            "default_code": "",  # Empty SKU
            "description": "",
            "description_sale": "",
            "list_price": 10.0,
            "standard_price": 5.0,
            "categ_id": (1, "General"),
            "image_1920": False,
            "barcode": None,
            "type": "product",
            "active": True,
            "attribute_line_ids": [],
            "product_variant_ids": [200],
            "product_variant_count": 1,
            "weight": 0,
            "taxes_id": [],
        }
        result = service._sync_single_product(product)
        assert result.action == "skipped"
        assert "No SKU" in result.message

    def test_sync_product_creates_new(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_odoo_product: dict[str, Any],
    ):
        """New products should be created in WooCommerce."""
        # Mock WooCommerce create
        mock_woo.create_product.return_value = {"id": 500}
        mock_woo.find_category_by_name.return_value = {"id": 5, "name": "Decking"}

        # Mock Odoo variant for stock
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": 50}]

        service = ProductSyncService(mock_odoo, mock_woo, db_session)
        result = service._sync_single_product(sample_odoo_product)

        assert result.action == "created"
        assert result.woo_product_id == 500
        assert result.sku == "DECK-001"

        # Verify mapping was created
        repo = ProductMappingRepository(db_session)
        mapping = repo.get_by_sku("DECK-001")
        assert mapping is not None
        assert mapping.woo_product_id == 500
        assert mapping.sync_status == SyncStatus.SYNCED

    def test_sync_product_updates_existing(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_odoo_product: dict[str, Any],
        sample_product_mapping: ProductMapping,
    ):
        """Existing products should be updated in WooCommerce."""
        mock_woo.update_product.return_value = {"id": 500}
        mock_woo.find_category_by_name.return_value = {"id": 5, "name": "Decking"}
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": 50}]

        service = ProductSyncService(mock_odoo, mock_woo, db_session)
        result = service._sync_single_product(sample_odoo_product)

        assert result.action == "updated"
        assert result.woo_product_id == 500
        mock_woo.update_product.assert_called_once()

    def test_sync_product_api_error_creates_failed_job(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_odoo_product: dict[str, Any],
    ):
        """API errors should create a failed job for retry."""
        from app.services.woo_client import WooCommerceAPIError
        mock_woo.create_product.side_effect = WooCommerceAPIError("Connection timeout")
        mock_woo.find_category_by_name.return_value = None
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": 50}]

        service = ProductSyncService(mock_odoo, mock_woo, db_session)
        result = service._sync_single_product(sample_odoo_product)

        assert result.action == "failed"
        assert "Connection timeout" in result.message

    def test_sync_variable_product(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_odoo_variable_product: dict[str, Any],
    ):
        """Variable products should trigger variant sync."""
        mock_woo.create_product.return_value = {"id": 501}
        mock_woo.find_category_by_name.return_value = {"id": 6, "name": "Turf"}
        mock_odoo.search_read.return_value = []
        mock_odoo.get_product_variants.return_value = []

        service = ProductSyncService(mock_odoo, mock_woo, db_session)

        # Mock the variant sync to avoid complex setup
        service.variant_sync.sync_variants = MagicMock(
            return_value={"synced": 3, "failed": 0, "skipped": 0}
        )
        service.variant_sync.build_woo_attributes_from_odoo = MagicMock(
            return_value=[{"name": "Thickness", "options": ["20mm", "30mm"]}]
        )

        result = service._sync_single_product(sample_odoo_variable_product)

        assert result.action == "created"
        assert result.variants_synced == 3

    def test_build_woo_product_data(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_odoo_product: dict[str, Any],
    ):
        """Test WooCommerce product data construction."""
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": 75}]

        service = ProductSyncService(mock_odoo, mock_woo, db_session)
        service.variant_sync.build_woo_attributes_from_odoo = MagicMock(return_value=[])

        data = service._build_woo_product_data(sample_odoo_product, "simple", "DECK-001")

        assert data["name"] == "Premium Deck Board"
        assert data["sku"] == "DECK-001"
        assert data["regular_price"] == "49.95"
        assert data["type"] == "simple"
        assert data["manage_stock"] is True
        assert data["tax_class"] == "GST"
        assert data["stock_quantity"] == 75


class TestPricelistPricing:
    """Tests for OdooPricelistHelper price calculations and resolution."""

    def test_pricelist_fixed_price(self, mock_odoo: MagicMock):
        """Pricelist helper should fetch and apply fixed price correctly."""
        from app.services.product_sync import OdooPricelistHelper

        # Mock pricelist items response
        mock_odoo.search_read.return_value = [
            {
                "id": 1,
                "applied_on": "0_product_variant",
                "product_tmpl_id": [10, "Template A"],
                "product_id": [100, "Variant A"],
                "categ_id": False,
                "compute_price": "fixed",
                "fixed_price": 88.0,
                "percent_price": 0.0,
                "price_discount": 0.0,
                "price_surcharge": 0.0,
                "base": "list_price",
            },
            {
                "id": 2,
                "applied_on": "1_product",
                "product_tmpl_id": [11, "Template B"],
                "product_id": False,
                "categ_id": False,
                "compute_price": "fixed",
                "fixed_price": 77.0,
                "percent_price": 0.0,
                "price_discount": 0.0,
                "price_surcharge": 0.0,
                "base": "list_price",
            },
        ]

        helper = OdooPricelistHelper(mock_odoo, 5)
        helper.load()

        assert helper.is_loaded is True
        # Variant A should match variant fixed price
        assert helper.get_price(10, 100, 100.0) == 88.0
        # Variant B of Template B should match template fixed price
        assert helper.get_price(11, 101, 100.0) == 77.0
        # Unknown template/variant should fall back to base price
        assert helper.get_price(12, 102, 100.0) == 100.0

    def test_pricelist_percentage_and_formula(self, mock_odoo: MagicMock):
        """Pricelist helper should calculate percentage and formula discounts correctly."""
        from app.services.product_sync import OdooPricelistHelper

        mock_odoo.search_read.return_value = [
            {
                "id": 1,
                "applied_on": "1_product",
                "product_tmpl_id": [10, "Template A"],
                "product_id": False,
                "categ_id": False,
                "compute_price": "percentage",
                "fixed_price": 0.0,
                "percent_price": 15.0,  # 15% off
                "price_discount": 0.0,
                "price_surcharge": 0.0,
                "base": "list_price",
            },
            {
                "id": 2,
                "applied_on": "1_product",
                "product_tmpl_id": [11, "Template B"],
                "product_id": False,
                "categ_id": False,
                "compute_price": "formula",
                "fixed_price": 0.0,
                "percent_price": 0.0,
                "price_discount": 10.0,  # 10% off
                "price_surcharge": 5.0,   # + $5 surcharge
                "base": "list_price",
            },
        ]

        helper = OdooPricelistHelper(mock_odoo, 5)
        helper.load()

        # 15% discount on $200 should be $170
        assert helper.get_price(10, None, 200.0) == 170.0

        # Formula calculation: 200 * (1 - 0.10) + 5 = 180 + 5 = 185.0
        assert helper.get_price(11, None, 200.0) == 185.0

    def test_pricelist_category_and_global(self, mock_odoo: MagicMock):
        """Pricelist helper should resolve category and global rules correctly."""
        from app.services.product_sync import OdooPricelistHelper

        mock_odoo.search_read.return_value = [
            {
                "id": 1,
                "applied_on": "2_product_category",
                "product_tmpl_id": False,
                "product_id": False,
                "categ_id": [5, "Category A"],
                "compute_price": "fixed",
                "fixed_price": 50.0,
                "percent_price": 0.0,
                "price_discount": 0.0,
                "price_surcharge": 0.0,
                "base": "list_price",
            },
            {
                "id": 2,
                "applied_on": "3_global",
                "product_tmpl_id": False,
                "product_id": False,
                "categ_id": False,
                "compute_price": "fixed",
                "fixed_price": 10.0,
                "percent_price": 0.0,
                "price_discount": 0.0,
                "price_surcharge": 0.0,
                "base": "list_price",
            },
        ]

        helper = OdooPricelistHelper(mock_odoo, 5)
        helper.load()

        # Category rule matches
        assert helper.get_price(10, None, 100.0, category_id=5) == 50.0

        # Global rule matches when category doesn't match
        assert helper.get_price(10, None, 100.0, category_id=6) == 10.0


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

        data = service._build_woo_product_data(sample_odoo_product, "simple")

        assert data["name"] == "Premium Deck Board"
        assert data["sku"] == "DECK-001"
        assert data["regular_price"] == "49.95"
        assert data["type"] == "simple"
        assert data["manage_stock"] is True
        assert data["tax_class"] == "GST"
        assert data["stock_quantity"] == 75

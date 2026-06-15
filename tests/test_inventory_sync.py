"""
TrueBuild — Inventory Sync Unit Tests.

Tests the inventory synchronization service.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.database.models import ProductMapping, SyncStatus, VariantMapping
from app.services.inventory_sync import InventorySyncService


class TestInventorySync:
    """Tests for InventorySyncService."""

    def test_sync_simple_product_stock(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_product_mapping: ProductMapping,
    ):
        """Test stock sync for a simple product."""
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": 42}]
        mock_woo.update_stock.return_value = {"id": 500, "stock_quantity": 42}

        service = InventorySyncService(mock_odoo, mock_woo, db_session)
        service._sync_simple_product_stock(sample_product_mapping)

        mock_woo.update_stock.assert_called_once_with(500, 42)

    def test_sync_simple_product_negative_stock_clipped(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_product_mapping: ProductMapping,
    ):
        """Negative stock should be clipped to 0."""
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": -5}]
        mock_woo.update_stock.return_value = {"id": 500, "stock_quantity": 0}

        service = InventorySyncService(mock_odoo, mock_woo, db_session)
        service._sync_simple_product_stock(sample_product_mapping)

        mock_woo.update_stock.assert_called_once_with(500, 0)

    def test_sync_variable_product_stock(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Test stock sync for a variable product with variants."""
        # Create variable product mapping
        product = ProductMapping(
            odoo_product_id=101,
            woo_product_id=501,
            sku="TURF-001",
            product_type="variable",
            sync_status=SyncStatus.SYNCED,
        )
        db_session.add(product)
        db_session.flush()

        # Create variant mappings
        variant = VariantMapping(
            product_mapping_id=product.id,
            odoo_variant_id=201,
            woo_variant_id=601,
            sku="TURF-001-20-GRN",
            sync_status=SyncStatus.SYNCED,
        )
        db_session.add(variant)
        db_session.flush()

        mock_odoo.search_read.return_value = [{"id": 201, "qty_available": 100}]
        mock_woo.update_variation_stock.return_value = {"id": 601, "stock_quantity": 100}

        service = InventorySyncService(mock_odoo, mock_woo, db_session)
        service._sync_variable_product_stock(product)

        mock_woo.update_variation_stock.assert_called_once_with(501, 601, 100)

    def test_sync_all_inventory(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_product_mapping: ProductMapping,
    ):
        """Test full inventory sync processes all mapped products."""
        mock_odoo.search_read.return_value = [{"id": 200, "qty_available": 50}]
        mock_woo.update_stock.return_value = {"id": 500, "stock_quantity": 50}

        service = InventorySyncService(mock_odoo, mock_woo, db_session)
        result = service.sync_all_inventory()

        assert result.total_products >= 1
        assert result.updated >= 1

    def test_sync_product_inventory_not_found(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Test single product inventory sync with unknown SKU."""
        service = InventorySyncService(mock_odoo, mock_woo, db_session)
        result = service.sync_product_inventory("NONEXISTENT")

        assert result["status"] == "skipped"

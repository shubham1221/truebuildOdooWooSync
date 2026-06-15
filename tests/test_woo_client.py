"""
TrueBuild — WooCommerce Client Unit Tests.

Tests the WooCommerce REST API client with mocked HTTP responses.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.services.woo_client import WooCommerceClient, WooCommerceAPIError


class TestWooCommerceClient:
    """Tests for WooCommerceClient."""

    def test_build_url(self):
        """Test URL construction."""
        client = WooCommerceClient(
            url="https://test.com",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        url = client._build_url("products")
        assert url == "https://test.com/wp-json/wc/v3/products"

    def test_build_url_strips_leading_slash(self):
        """Test URL strips leading slash from endpoint."""
        client = WooCommerceClient(
            url="https://test.com",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        url = client._build_url("/products")
        assert url == "https://test.com/wp-json/wc/v3/products"

    def test_add_auth_params(self):
        """Test OAuth params are added."""
        client = WooCommerceClient(
            url="https://test.com",
            consumer_key="ck_test",
            consumer_secret="cs_test",
        )
        params = client._add_auth_params({"per_page": 10})
        assert params["consumer_key"] == "ck_test"
        assert params["consumer_secret"] == "cs_test"
        assert params["per_page"] == 10

    def test_create_product(self, mock_woo):
        """Test product creation."""
        mock_woo.create_product = MagicMock(return_value={"id": 500, "sku": "TEST-001"})
        result = mock_woo.create_product({"name": "Test", "sku": "TEST-001"})
        assert result["id"] == 500
        assert result["sku"] == "TEST-001"

    def test_update_product(self, mock_woo):
        """Test product update."""
        mock_woo.update_product = MagicMock(return_value={"id": 500, "name": "Updated"})
        result = mock_woo.update_product(500, {"name": "Updated"})
        assert result["name"] == "Updated"

    def test_get_product_by_sku(self, mock_woo):
        """Test product lookup by SKU."""
        mock_woo.get_product_by_sku = MagicMock(return_value={"id": 500, "sku": "DECK-001"})
        result = mock_woo.get_product_by_sku("DECK-001")
        assert result["id"] == 500

    def test_get_product_by_sku_not_found(self, mock_woo):
        """Test product lookup by SKU returns None when not found."""
        mock_woo.get_product_by_sku = MagicMock(return_value=None)
        result = mock_woo.get_product_by_sku("NONEXISTENT")
        assert result is None

    def test_create_variation(self, mock_woo):
        """Test variation creation."""
        mock_woo.create_variation = MagicMock(return_value={"id": 601, "sku": "TURF-001-20"})
        result = mock_woo.create_variation(500, {"sku": "TURF-001-20"})
        assert result["id"] == 601

    def test_update_stock(self, mock_woo):
        """Test stock update."""
        mock_woo.update_stock = MagicMock(return_value={"id": 500, "stock_quantity": 50})
        result = mock_woo.update_stock(500, 50)
        assert result["stock_quantity"] == 50

    def test_check_connection(self, mock_woo):
        """Test health check."""
        mock_woo.check_connection = MagicMock(return_value={"status": "connected"})
        result = mock_woo.check_connection()
        assert result["status"] == "connected"

    def test_find_category_by_name(self, mock_woo):
        """Test category lookup by name."""
        mock_woo.find_category_by_name = MagicMock(return_value={"id": 10, "name": "Decking"})
        result = mock_woo.find_category_by_name("Decking")
        assert result["id"] == 10

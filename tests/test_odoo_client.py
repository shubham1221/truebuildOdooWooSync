"""
TrueBuild — Odoo Client Unit Tests.

Tests the Odoo XML-RPC client wrapper with mocked xmlrpc calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.services.odoo_client import OdooClient, OdooAPIError


class TestOdooClient:
    """Tests for OdooClient."""

    @patch("app.services.odoo_client.xmlrpc.client.ServerProxy")
    def test_authenticate_success(self, mock_proxy):
        """Test successful authentication returns uid."""
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 42
        mock_proxy.return_value = mock_common

        client = OdooClient(
            url="https://test.odoo.com",
            db="test",
            username="user@test.com",
            password="password",
        )
        uid = client.authenticate()
        assert uid == 42

    @patch("app.services.odoo_client.xmlrpc.client.ServerProxy")
    def test_authenticate_failure(self, mock_proxy):
        """Test authentication failure raises OdooAPIError."""
        mock_common = MagicMock()
        mock_common.authenticate.return_value = False
        mock_proxy.return_value = mock_common

        client = OdooClient(
            url="https://test.odoo.com",
            db="test",
            username="user@test.com",
            password="wrong-password",
        )
        with pytest.raises(OdooAPIError, match="Authentication failed"):
            client.authenticate()

    def test_search_read(self, mock_odoo):
        """Test search_read delegates correctly."""
        mock_odoo.search_read = MagicMock(return_value=[{"id": 1, "name": "Test"}])
        result = mock_odoo.search_read("product.template", [], ["name"])
        assert len(result) == 1
        assert result[0]["name"] == "Test"

    def test_create(self, mock_odoo):
        """Test create returns record ID."""
        mock_odoo.create = MagicMock(return_value=42)
        result = mock_odoo.create("product.template", {"name": "Test"})
        assert result == 42

    def test_write(self, mock_odoo):
        """Test write returns True."""
        mock_odoo.write = MagicMock(return_value=True)
        result = mock_odoo.write("product.template", [1], {"name": "Updated"})
        assert result is True

    def test_check_connection(self, mock_odoo):
        """Test health check returns status dict."""
        mock_odoo.check_connection = MagicMock(return_value={
            "status": "connected",
            "server_version": "17.0",
        })
        result = mock_odoo.check_connection()
        assert result["status"] == "connected"

    def test_get_product_templates(self, mock_odoo):
        """Test fetching product templates."""
        mock_odoo.get_product_templates = MagicMock(return_value=[
            {"id": 1, "name": "Product A", "default_code": "SKU-001"},
        ])
        result = mock_odoo.get_product_templates()
        assert len(result) == 1
        assert result[0]["default_code"] == "SKU-001"

    def test_create_sale_order(self, mock_odoo):
        """Test creating a sale order."""
        mock_odoo.create_sale_order = MagicMock(return_value=100)
        result = mock_odoo.create_sale_order({
            "partner_id": 1,
            "order_line": [(0, 0, {"product_id": 1, "product_uom_qty": 1})],
        })
        assert result == 100

    def test_confirm_sale_order(self, mock_odoo):
        """Test confirming a sale order."""
        mock_odoo.confirm_sale_order = MagicMock(return_value=True)
        result = mock_odoo.confirm_sale_order(100)
        assert result is True

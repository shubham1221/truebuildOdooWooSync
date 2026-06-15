"""
TrueBuild — Order Sync Unit Tests.

Tests the order synchronization service with mocked APIs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from app.database.models import OrderMapping, OrderStatus, ProductMapping
from app.services.order_sync import OrderSyncService


class TestOrderSync:
    """Tests for OrderSyncService."""

    def test_parse_woo_order(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_woo_order: dict[str, Any],
    ):
        """Test WooCommerce order parsing."""
        service = OrderSyncService(mock_odoo, mock_woo, db_session)
        order_data = service._parse_woo_order(sample_woo_order)

        assert order_data.woo_order_id == 5001
        assert order_data.order_number == "5001"
        assert order_data.total == "99.90"
        assert order_data.currency == "AUD"
        assert order_data.billing_email == "john@example.com.au"
        assert order_data.billing_first_name == "John"
        assert order_data.billing_state == "VIC"
        assert len(order_data.line_items) == 1
        assert order_data.line_items[0].sku == "DECK-001"
        assert order_data.line_items[0].quantity == 2

    def test_sync_order_idempotent(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Duplicate orders should be skipped."""
        # Create existing mapping
        existing = OrderMapping(
            woo_order_id=5001,
            odoo_order_id=100,
            order_number="5001",
            status=OrderStatus.SYNCED,
        )
        db_session.add(existing)
        db_session.flush()

        service = OrderSyncService(mock_odoo, mock_woo, db_session)
        result = service.sync_order(5001)

        assert result.action == "skipped"
        assert result.odoo_order_id == 100

    def test_sync_order_creates_sale_order(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
        sample_woo_order: dict[str, Any],
        sample_product_mapping,
        sample_variant_mapping,
    ):
        """Test full order sync creates sale order in Odoo."""
        # Mock WooCommerce get_order
        mock_woo.get_order.return_value = sample_woo_order

        # Mock Odoo operations
        mock_odoo.find_partner_by_email.return_value = [{"id": 50, "name": "John Smith", "email": "john@example.com.au"}]
        mock_odoo.create_sale_order.return_value = 200
        mock_odoo.confirm_sale_order.return_value = True
        mock_odoo.create_invoice_from_order.return_value = [300]
        mock_odoo.post_invoice.return_value = True
        mock_odoo.search_read.return_value = [{"id": 200}]

        service = OrderSyncService(mock_odoo, mock_woo, db_session)
        result = service.sync_order(5001)

        assert result.action == "created"
        assert result.odoo_order_id == 200
        assert result.odoo_invoice_id == 300
        mock_odoo.create_sale_order.assert_called_once()
        mock_odoo.confirm_sale_order.assert_called_once_with(200)

    def test_sync_order_missing_sku_fails(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Orders with unmapped SKUs should fail."""
        order_payload = {
            "id": 5002,
            "number": "5002",
            "status": "processing",
            "currency": "AUD",
            "total": "50.00",
            "total_tax": "4.55",
            "shipping_total": "0.00",
            "discount_total": "0.00",
            "payment_method": "paypal",
            "payment_method_title": "PayPal",
            "customer_note": "",
            "date_created": "2026-06-15T10:00:00",
            "billing": {"email": "test@test.com", "first_name": "Test", "last_name": "User",
                       "phone": "", "company": "", "address_1": "", "address_2": "",
                       "city": "", "state": "", "postcode": "", "country": "AU"},
            "shipping": {"first_name": "", "last_name": "", "address_1": "", "address_2": "",
                        "city": "", "state": "", "postcode": "", "country": "AU"},
            "line_items": [
                {"id": 1, "product_id": 999, "variation_id": 0, "sku": "NONEXISTENT",
                 "name": "Unknown Product", "quantity": 1, "price": "50.00",
                 "subtotal": "50.00", "total": "50.00", "total_tax": "4.55"},
            ],
        }
        mock_woo.get_order.return_value = order_payload
        mock_odoo.find_partner_by_email.return_value = [{"id": 50}]

        service = OrderSyncService(mock_odoo, mock_woo, db_session)
        result = service.sync_order(5002)

        assert result.action == "failed"
        assert "NONEXISTENT" in result.message or "not found" in result.message.lower()

    def test_handle_order_cancelled(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Test order cancellation handling."""
        mapping = OrderMapping(
            woo_order_id=5003,
            odoo_order_id=300,
            order_number="5003",
            status=OrderStatus.SYNCED,
        )
        db_session.add(mapping)
        db_session.flush()

        mock_odoo.execute_kw.return_value = True

        service = OrderSyncService(mock_odoo, mock_woo, db_session)
        result = service.handle_order_cancelled(5003)

        assert result.action == "cancelled"

    def test_handle_order_refunded(
        self,
        db_session: Session,
        mock_odoo: MagicMock,
        mock_woo: MagicMock,
    ):
        """Test order refund handling."""
        mapping = OrderMapping(
            woo_order_id=5004,
            odoo_order_id=400,
            order_number="5004",
            status=OrderStatus.SYNCED,
        )
        db_session.add(mapping)
        db_session.flush()

        service = OrderSyncService(mock_odoo, mock_woo, db_session)
        result = service.handle_order_refunded(5004)

        assert result.action == "refunded"

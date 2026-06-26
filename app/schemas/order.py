"""
TrueBuild Integration Platform — Order Schemas.

Pydantic V2 schemas for order sync data validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OrderLineItem(BaseModel):
    """A single line item from a WooCommerce order."""

    woo_line_id: int
    product_id: int
    variation_id: int = 0
    sku: str = ""
    name: str = ""
    quantity: int = 1
    price: str = "0.00"
    subtotal: str = "0.00"
    total: str = "0.00"
    total_tax: str = "0.00"


class OrderSyncData(BaseModel):
    """Validated order data ready for Odoo sync."""

    woo_order_id: int
    order_number: str = ""
    status: str = ""
    currency: str = "AUD"
    total: str = "0.00"
    total_tax: str = "0.00"
    shipping_total: str = "0.00"
    discount_total: str = "0.00"
    payment_method: str = ""
    payment_method_title: str = ""
    customer_note: str = ""
    date_created: str = ""
    line_items: list[OrderLineItem] = Field(default_factory=list)
    billing_email: str = ""
    billing_first_name: str = ""
    billing_last_name: str = ""
    billing_phone: str = ""
    billing_company: str = ""
    billing_address_1: str = ""
    billing_address_2: str = ""
    billing_city: str = ""
    billing_state: str = ""
    billing_postcode: str = ""
    billing_country: str = "AU"
    shipping_first_name: str = ""
    shipping_last_name: str = ""
    shipping_phone: str = ""
    shipping_company: str = ""
    shipping_address_1: str = ""
    shipping_address_2: str = ""
    shipping_city: str = ""
    shipping_state: str = ""
    shipping_postcode: str = ""
    shipping_country: str = "AU"


class OrderMappingResponse(BaseModel):
    """API response for an order mapping."""

    id: int
    woo_order_id: int
    odoo_order_id: int | None
    order_number: str | None
    odoo_invoice_id: int | None
    status: str
    total_amount: str | None
    currency: str | None
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderSyncResult(BaseModel):
    """Result of an order sync operation."""

    woo_order_id: int
    odoo_order_id: int | None = None
    odoo_invoice_id: int | None = None
    action: str = ""  # created | skipped | failed
    message: str = ""

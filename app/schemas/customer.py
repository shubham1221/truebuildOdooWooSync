"""
TrueBuild Integration Platform — Customer Schemas.

Pydantic V2 schemas for customer sync data validation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CustomerData(BaseModel):
    """Customer data extracted from a WooCommerce order."""

    email: str
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    company: str = ""
    address_1: str = ""
    address_2: str = ""
    city: str = ""
    state: str = ""
    postcode: str = ""
    country: str = "AU"
    woo_customer_id: int | None = None


class CustomerMappingResponse(BaseModel):
    """API response for a customer mapping."""

    id: int
    odoo_partner_id: int
    woo_customer_id: int | None
    email: str
    first_name: str | None
    last_name: str | None
    last_sync_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

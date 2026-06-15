"""
TrueBuild Integration Platform — Product Schemas.

Pydantic V2 schemas for product sync data validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProductAttribute(BaseModel):
    """A product attribute (e.g., Color, Size)."""

    name: str
    options: list[str] = Field(default_factory=list)
    visible: bool = True
    variation: bool = True
    position: int = 0


class ProductVariantData(BaseModel):
    """Data for a single product variant."""

    odoo_variant_id: int
    sku: str
    regular_price: str = "0.00"
    manage_stock: bool = True
    stock_quantity: int = 0
    weight: str = ""
    attributes: list[dict[str, str]] = Field(default_factory=list)
    image_base64: str | None = None


class ProductSyncData(BaseModel):
    """Validated product data ready for WooCommerce sync."""

    odoo_template_id: int
    name: str
    sku: str
    description: str = ""
    short_description: str = ""
    regular_price: str = "0.00"
    cost_price: float = 0.0
    category_name: str = ""
    category_id: int | None = None
    product_type: str = "simple"  # simple | variable
    manage_stock: bool = True
    stock_quantity: int = 0
    weight: str = ""
    barcode: str | None = None
    tax_class: str = "GST"
    taxable: bool = True
    image_base64: str | None = None
    gallery_images: list[str] = Field(default_factory=list)
    attributes: list[ProductAttribute] = Field(default_factory=list)
    variants: list[ProductVariantData] = Field(default_factory=list)


class ProductMappingResponse(BaseModel):
    """API response for a product mapping."""

    id: int
    odoo_product_id: int
    woo_product_id: int | None
    sku: str
    product_type: str
    sync_status: str
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class VariantMappingResponse(BaseModel):
    """API response for a variant mapping."""

    id: int
    product_mapping_id: int
    odoo_variant_id: int
    woo_variant_id: int | None
    sku: str
    sync_status: str
    last_sync_at: datetime | None

    model_config = {"from_attributes": True}


class ProductSyncResult(BaseModel):
    """Result of a product sync operation."""

    sku: str
    odoo_product_id: int
    woo_product_id: int | None = None
    action: str = ""  # created | updated | skipped | failed
    message: str = ""
    variants_synced: int = 0
    variants_failed: int = 0


class ProductSyncSummary(BaseModel):
    """Summary of a full product sync run."""

    total_products: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    results: list[ProductSyncResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

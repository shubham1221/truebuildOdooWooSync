"""
TrueBuild Integration Platform — Test Fixtures.

Shared pytest fixtures for database sessions, mock API clients,
and test data factories.
"""

from __future__ import annotations

import os
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Set test environment before importing app modules
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ODOO_URL", "https://test.odoo.com")
os.environ.setdefault("ODOO_DB", "test")
os.environ.setdefault("ODOO_USERNAME", "test@test.com")
os.environ.setdefault("ODOO_PASSWORD", "test-password")
os.environ.setdefault("WOO_URL", "https://test.woocommerce.com")
os.environ.setdefault("WOO_CONSUMER_KEY", "ck_test")
os.environ.setdefault("WOO_CONSUMER_SECRET", "cs_test")
os.environ.setdefault("WOO_WEBHOOK_SECRET", "webhook-test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.database.db import Base
from app.database.models import (
    CustomerMapping,
    FailedJob,
    OrderMapping,
    ProductMapping,
    SyncLog,
    VariantMapping,
)


# ── Database Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def test_engine():
    """Create a test database engine (SQLite in-memory)."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    """Provide a transactional database session for each test."""
    TestSession = sessionmaker(bind=test_engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ── Mock API Client Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def mock_odoo() -> MagicMock:
    """Create a mock Odoo client."""
    odoo = MagicMock()
    odoo.authenticate.return_value = 1
    odoo.url = "https://test.odoo.com"
    odoo.db = "test"
    return odoo


@pytest.fixture
def mock_woo() -> MagicMock:
    """Create a mock WooCommerce client."""
    woo = MagicMock()
    woo.url = "https://test.woocommerce.com"
    return woo


# ── Test Data Factories ──────────────────────────────────────────────────────


@pytest.fixture
def sample_odoo_product() -> dict[str, Any]:
    """Sample Odoo product.template data."""
    return {
        "id": 100,
        "name": "Premium Deck Board",
        "default_code": "DECK-001",
        "description": "High quality composite deck board",
        "description_sale": "Premium composite decking",
        "list_price": 49.95,
        "standard_price": 25.00,
        "categ_id": (5, "Decking"),
        "image_1920": False,
        "barcode": "9876543210123",
        "type": "product",
        "active": True,
        "attribute_line_ids": [],
        "product_variant_ids": [200],
        "product_variant_count": 1,
        "weight": 2.5,
        "taxes_id": [1],
    }


@pytest.fixture
def sample_odoo_variable_product() -> dict[str, Any]:
    """Sample Odoo variable product with attributes."""
    return {
        "id": 101,
        "name": "Artificial Turf Roll",
        "default_code": "TURF-001",
        "description": "Premium artificial turf",
        "description_sale": "Lush green artificial turf",
        "list_price": 29.95,
        "standard_price": 15.00,
        "categ_id": (6, "Turf"),
        "image_1920": False,
        "barcode": None,
        "type": "product",
        "active": True,
        "attribute_line_ids": [10, 11],
        "product_variant_ids": [201, 202, 203],
        "product_variant_count": 3,
        "weight": 5.0,
        "taxes_id": [1],
    }


@pytest.fixture
def sample_odoo_variant() -> dict[str, Any]:
    """Sample Odoo product.product variant data."""
    return {
        "id": 201,
        "name": "Artificial Turf Roll - 20mm - Green",
        "default_code": "TURF-001-20-GRN",
        "lst_price": 29.95,
        "standard_price": 15.00,
        "barcode": None,
        "weight": 5.0,
        "qty_available": 100.0,
        "product_template_attribute_value_ids": [50, 51],
        "image_variant_1920": False,
        "active": True,
    }


@pytest.fixture
def sample_woo_order() -> dict[str, Any]:
    """Sample WooCommerce order payload."""
    return {
        "id": 5001,
        "number": "5001",
        "status": "processing",
        "currency": "AUD",
        "total": "99.90",
        "total_tax": "9.08",
        "shipping_total": "0.00",
        "discount_total": "0.00",
        "payment_method": "stripe",
        "payment_method_title": "Credit Card",
        "customer_note": "Please deliver to back door",
        "date_created": "2026-06-15T10:00:00",
        "billing": {
            "first_name": "John",
            "last_name": "Smith",
            "email": "john@example.com.au",
            "phone": "0412345678",
            "company": "",
            "address_1": "123 Main Street",
            "address_2": "",
            "city": "Melbourne",
            "state": "VIC",
            "postcode": "3000",
            "country": "AU",
        },
        "shipping": {
            "first_name": "John",
            "last_name": "Smith",
            "address_1": "123 Main Street",
            "address_2": "",
            "city": "Melbourne",
            "state": "VIC",
            "postcode": "3000",
            "country": "AU",
        },
        "line_items": [
            {
                "id": 1,
                "product_id": 500,
                "variation_id": 0,
                "sku": "DECK-001",
                "name": "Premium Deck Board",
                "quantity": 2,
                "price": "49.95",
                "subtotal": "99.90",
                "total": "99.90",
                "total_tax": "9.08",
            }
        ],
    }


@pytest.fixture
def sample_product_mapping(db_session: Session) -> ProductMapping:
    """Create a sample product mapping in the test database."""
    mapping = ProductMapping(
        odoo_product_id=100,
        woo_product_id=500,
        sku="DECK-001",
        product_type="simple",
        sync_status="synced",
    )
    db_session.add(mapping)
    db_session.flush()
    return mapping


@pytest.fixture
def sample_variant_mapping(
    db_session: Session,
    sample_product_mapping: ProductMapping,
) -> VariantMapping:
    """Create a sample variant mapping in the test database."""
    mapping = VariantMapping(
        product_mapping_id=sample_product_mapping.id,
        odoo_variant_id=200,
        woo_variant_id=600,
        sku="DECK-001",
        sync_status="synced",
    )
    db_session.add(mapping)
    db_session.flush()
    return mapping


@pytest.fixture
def sample_customer_mapping(db_session: Session) -> CustomerMapping:
    """Create a sample customer mapping in the test database."""
    mapping = CustomerMapping(
        odoo_partner_id=50,
        woo_customer_id=100,
        email="john@example.com.au",
        first_name="John",
        last_name="Smith",
    )
    db_session.add(mapping)
    db_session.flush()
    return mapping

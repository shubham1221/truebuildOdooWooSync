"""
TrueBuild Integration Platform — FastAPI Dependencies.

Dependency injection for database sessions, API clients, and services.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.database.db import get_db
from app.services.odoo_client import OdooClient
from app.services.woo_client import WooCommerceClient


def get_odoo_client() -> OdooClient:
    """Get an authenticated Odoo client."""
    client = OdooClient()
    client.authenticate()
    return client


def get_woo_client() -> WooCommerceClient:
    """Get a WooCommerce client."""
    return WooCommerceClient()

"""
TrueBuild Integration Platform — Health Check Endpoint.

Checks connectivity to PostgreSQL, Redis, Odoo, and WooCommerce.
"""

from __future__ import annotations

from typing import Any

import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.database.db import get_db
from app.services.odoo_client import OdooClient
from app.services.woo_client import WooCommerceClient
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Comprehensive health check endpoint.

    Checks:
    - PostgreSQL database connectivity
    - Redis connectivity
    - Odoo API connectivity
    - WooCommerce API connectivity
    """
    settings = get_settings()
    health: dict[str, Any] = {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }

    all_healthy = True

    # ── Database Check ───────────────────────────────────────────────
    try:
        db.execute(text("SELECT 1"))
        health["database"] = {"status": "connected"}
    except Exception as e:
        health["database"] = {"status": "error", "error": str(e)}
        all_healthy = False

    # ── Redis Check ──────────────────────────────────────────────────
    try:
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        health["redis"] = {"status": "connected"}
    except Exception as e:
        health["redis"] = {"status": "error", "error": str(e)}
        all_healthy = False

    # ── Odoo Check ───────────────────────────────────────────────────
    try:
        odoo = OdooClient()
        health["odoo"] = odoo.check_connection()
    except Exception as e:
        health["odoo"] = {"status": "error", "error": str(e)}
        all_healthy = False

    # ── WooCommerce Check ────────────────────────────────────────────
    try:
        woo = WooCommerceClient()
        health["woocommerce"] = woo.check_connection()
    except Exception as e:
        health["woocommerce"] = {"status": "error", "error": str(e)}
        all_healthy = False

    if not all_healthy:
        health["status"] = "degraded"

    return health

"""
TrueBuild Integration Platform — Order Sync Celery Tasks.

Background tasks for order processing from WooCommerce webhooks.
"""

from __future__ import annotations

from typing import Any

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="app.tasks.order_tasks.process_order_webhook",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def process_order_webhook(self, payload: dict[str, Any]) -> dict:
    """
    Celery task: Process a WooCommerce order webhook payload.

    Creates a Sales Order in Odoo with customer, line items, and invoice.
    """
    woo_order_id = payload.get("id", 0)
    logger.info(
        "celery_order_webhook_started",
        woo_order_id=woo_order_id,
        task_id=self.request.id,
    )

    try:
        from app.database.db import get_session_factory
        from app.services.odoo_client import OdooClient
        from app.services.woo_client import WooCommerceClient
        from app.services.order_sync import OrderSyncService

        session_factory = get_session_factory()
        db = session_factory()
        try:
            odoo = OdooClient()
            odoo.authenticate()
            woo = WooCommerceClient()
            service = OrderSyncService(odoo, woo, db)
            result = service.sync_order_from_payload(payload)

            logger.info(
                "celery_order_webhook_completed",
                woo_order_id=woo_order_id,
                action=result.action,
                odoo_order_id=result.odoo_order_id,
            )
            return result.model_dump()
        finally:
            db.close()

    except Exception as e:
        logger.error(
            "celery_order_webhook_error",
            woo_order_id=woo_order_id,
            error=str(e),
            exc_info=True,
        )
        raise self.retry(exc=e)


@celery_app.task(
    name="app.tasks.order_tasks.process_order_cancellation",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_order_cancellation(self, woo_order_id: int) -> dict:
    """Celery task: Process a WooCommerce order cancellation."""
    logger.info("celery_order_cancellation_started", woo_order_id=woo_order_id)

    try:
        from app.database.db import get_session_factory
        from app.services.odoo_client import OdooClient
        from app.services.woo_client import WooCommerceClient
        from app.services.order_sync import OrderSyncService

        session_factory = get_session_factory()
        db = session_factory()
        try:
            odoo = OdooClient()
            odoo.authenticate()
            woo = WooCommerceClient()
            service = OrderSyncService(odoo, woo, db)
            result = service.handle_order_cancelled(woo_order_id)
            return result.model_dump()
        finally:
            db.close()

    except Exception as e:
        logger.error("celery_order_cancellation_error", woo_order_id=woo_order_id, error=str(e))
        raise self.retry(exc=e)


@celery_app.task(
    name="app.tasks.order_tasks.process_order_refund",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_order_refund(self, woo_order_id: int) -> dict:
    """Celery task: Process a WooCommerce order refund."""
    logger.info("celery_order_refund_started", woo_order_id=woo_order_id)

    try:
        from app.database.db import get_session_factory
        from app.services.odoo_client import OdooClient
        from app.services.woo_client import WooCommerceClient
        from app.services.order_sync import OrderSyncService

        session_factory = get_session_factory()
        db = session_factory()
        try:
            odoo = OdooClient()
            odoo.authenticate()
            woo = WooCommerceClient()
            service = OrderSyncService(odoo, woo, db)
            result = service.handle_order_refunded(woo_order_id)
            return result.model_dump()
        finally:
            db.close()

    except Exception as e:
        logger.error("celery_order_refund_error", woo_order_id=woo_order_id, error=str(e))
        raise self.retry(exc=e)

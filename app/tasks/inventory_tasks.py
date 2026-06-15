"""
TrueBuild Integration Platform — Inventory Sync Celery Tasks.

Background tasks for inventory synchronization from Odoo to WooCommerce.
"""

from __future__ import annotations

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="app.tasks.inventory_tasks.sync_all_inventory",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def sync_all_inventory(self) -> dict:
    """
    Celery task: Sync all inventory from Odoo to WooCommerce.

    Runs on schedule (every 5 minutes) or triggered manually.
    """
    logger.info("celery_inventory_sync_started", task_id=self.request.id)

    try:
        from app.database.db import get_session_factory
        from app.services.odoo_client import OdooClient
        from app.services.woo_client import WooCommerceClient
        from app.services.inventory_sync import InventorySyncService

        session_factory = get_session_factory()
        db = session_factory()
        try:
            odoo = OdooClient()
            odoo.authenticate()
            woo = WooCommerceClient()
            service = InventorySyncService(odoo, woo, db)
            result = service.sync_all_inventory()

            logger.info(
                "celery_inventory_sync_completed",
                task_id=self.request.id,
                total=result.total_products,
                updated=result.updated,
                failed=result.failed,
            )
            return result.to_dict()
        finally:
            db.close()

    except Exception as e:
        logger.error(
            "celery_inventory_sync_error",
            task_id=self.request.id,
            error=str(e),
            exc_info=True,
        )
        raise self.retry(exc=e)

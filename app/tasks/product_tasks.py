"""
TrueBuild Integration Platform — Product Sync Celery Tasks.

Background tasks for product synchronization from Odoo to WooCommerce.
"""

from __future__ import annotations

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="app.tasks.product_tasks.sync_all_products",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def sync_all_products(self) -> dict:
    """
    Celery task: Sync all products from Odoo to WooCommerce.

    Runs on schedule (every 5 minutes) or triggered manually.
    """
    logger.info("celery_product_sync_started", task_id=self.request.id)

    try:
        from app.database.db import get_session_factory
        from app.services.odoo_client import OdooClient
        from app.services.woo_client import WooCommerceClient
        from app.services.product_sync import ProductSyncService

        session_factory = get_session_factory()
        db = session_factory()
        try:
            odoo = OdooClient()
            odoo.authenticate()
            woo = WooCommerceClient()
            service = ProductSyncService(odoo, woo, db)
            result = service.sync_all_products()

            logger.info(
                "celery_product_sync_completed",
                task_id=self.request.id,
                total=result.total_products,
                created=result.created,
                updated=result.updated,
                failed=result.failed,
            )
            return result.model_dump()
        finally:
            db.close()

    except Exception as e:
        logger.error(
            "celery_product_sync_error",
            task_id=self.request.id,
            error=str(e),
            exc_info=True,
        )
        raise self.retry(exc=e)


@celery_app.task(
    name="app.tasks.product_tasks.sync_single_product",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def sync_single_product(self, sku: str) -> dict:
    """Celery task: Sync a single product by SKU."""
    logger.info("celery_single_product_sync_started", sku=sku, task_id=self.request.id)

    try:
        from app.database.db import get_session_factory
        from app.services.odoo_client import OdooClient
        from app.services.woo_client import WooCommerceClient
        from app.services.product_sync import ProductSyncService

        session_factory = get_session_factory()
        db = session_factory()
        try:
            odoo = OdooClient()
            odoo.authenticate()
            woo = WooCommerceClient()
            service = ProductSyncService(odoo, woo, db)
            result = service.sync_product_by_sku(sku)
            return result.model_dump()
        finally:
            db.close()

    except Exception as e:
        logger.error("celery_single_product_sync_error", sku=sku, error=str(e))
        raise self.retry(exc=e)

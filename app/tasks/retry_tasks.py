"""
TrueBuild Integration Platform — Retry Queue Processor.

Processes failed jobs from the FailedJob table.
Implements exponential backoff: 1min → 5min → 15min → 1hr.
After max retries, moves jobs to dead letter queue.
"""

from __future__ import annotations

from app.tasks.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="app.tasks.retry_tasks.process_retry_queue",
    bind=True,
    acks_late=True,
)
def process_retry_queue(self) -> dict:
    """
    Celery task: Process all failed jobs that are ready for retry.

    Runs every minute via beat schedule.
    """
    logger.info("celery_retry_queue_started", task_id=self.request.id)

    processed = 0
    succeeded = 0
    failed_again = 0

    try:
        from app.database.db import get_session_factory
        from app.repositories.failed_job_repo import FailedJobRepository
        from app.config.settings import get_settings

        settings = get_settings()
        session_factory = get_session_factory()
        db = session_factory()

        try:
            repo = FailedJobRepository(db)
            ready_jobs = repo.get_ready_for_retry()

            for job in ready_jobs:
                processed += 1
                try:
                    _execute_retry(job, db)
                    repo.mark_resolved(job)
                    succeeded += 1
                    logger.info(
                        "retry_succeeded",
                        job_id=job.id,
                        job_type=job.job_type,
                        entity_id=job.entity_id,
                    )
                except Exception as e:
                    repo.increment_retry(
                        job,
                        error_message=str(e),
                        retry_delays=settings.RETRY_DELAYS_SECONDS,
                    )
                    failed_again += 1
                    logger.warning(
                        "retry_failed_again",
                        job_id=job.id,
                        job_type=job.job_type,
                        retry_count=job.retry_count,
                        error=str(e),
                    )

            db.commit()

        finally:
            db.close()

    except Exception as e:
        logger.error("retry_queue_error", error=str(e))

    result = {
        "processed": processed,
        "succeeded": succeeded,
        "failed_again": failed_again,
    }
    logger.info("celery_retry_queue_completed", **result)
    return result


@celery_app.task(
    name="app.tasks.retry_tasks.retry_single_job",
    bind=True,
)
def retry_single_job(self, job_id: int) -> dict:
    """Celery task: Retry a specific failed job by ID."""
    logger.info("celery_retry_single_started", job_id=job_id)

    try:
        from app.database.db import get_session_factory
        from app.repositories.failed_job_repo import FailedJobRepository
        from app.config.settings import get_settings

        settings = get_settings()
        session_factory = get_session_factory()
        db = session_factory()

        try:
            repo = FailedJobRepository(db)
            job = repo.get_by_id(job_id)

            if not job:
                return {"status": "not_found", "job_id": job_id}

            try:
                _execute_retry(job, db)
                repo.mark_resolved(job)
                db.commit()
                return {"status": "succeeded", "job_id": job_id}
            except Exception as e:
                repo.increment_retry(
                    job,
                    error_message=str(e),
                    retry_delays=settings.RETRY_DELAYS_SECONDS,
                )
                db.commit()
                return {"status": "failed", "job_id": job_id, "error": str(e)}
        finally:
            db.close()

    except Exception as e:
        logger.error("retry_single_error", job_id=job_id, error=str(e))
        return {"status": "error", "job_id": job_id, "error": str(e)}


def _execute_retry(job, db) -> None:
    """
    Execute the retry for a specific job type.

    Dispatches to the appropriate sync service based on job_type.
    """
    from app.services.odoo_client import OdooClient
    from app.services.woo_client import WooCommerceClient

    odoo = OdooClient()
    odoo.authenticate()
    woo = WooCommerceClient()

    payload = job.payload or {}

    if job.job_type == "product_sync":
        from app.services.product_sync import ProductSyncService
        service = ProductSyncService(odoo, woo, db)
        sku = payload.get("sku") or job.entity_id
        if sku:
            result = service.sync_product_by_sku(sku)
            if result.action == "failed":
                raise Exception(result.message)

    elif job.job_type == "order_sync":
        from app.services.order_sync import OrderSyncService
        service = OrderSyncService(odoo, woo, db)
        woo_order_id = payload.get("woo_order_id") or int(job.entity_id or 0)
        if woo_order_id:
            result = service.sync_order(woo_order_id)
            if result.action == "failed":
                raise Exception(result.message)

    elif job.job_type == "inventory_sync":
        from app.services.inventory_sync import InventorySyncService
        service = InventorySyncService(odoo, woo, db)
        sku = payload.get("sku") or job.entity_id
        if sku:
            result = service.sync_product_inventory(sku)
            if result.get("status") == "failed":
                raise Exception(result.get("message", "Inventory sync failed"))

    else:
        raise ValueError(f"Unknown job type: {job.job_type}")

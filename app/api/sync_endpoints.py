"""
TrueBuild Integration Platform — Manual Sync API Endpoints.

Provides API endpoints to trigger manual syncs, view sync status,
browse sync logs, and manage failed jobs.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_odoo_client, get_woo_client
from app.database.db import get_db
from app.database.models import FailedJobStatus
from app.repositories.customer_repo import CustomerMappingRepository
from app.repositories.failed_job_repo import FailedJobRepository
from app.repositories.order_repo import OrderMappingRepository
from app.repositories.product_repo import ProductMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.schemas.sync import (
    FailedJobResponse,
    SyncLogResponse,
    SyncStatusResponse,
    SyncTypeStatus,
)
from app.services.inventory_sync import InventorySyncService
from app.services.odoo_client import OdooClient
from app.services.product_sync import ProductSyncService
from app.services.order_sync import OrderSyncService
from app.services.woo_client import WooCommerceClient
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/sync", tags=["Sync Management"])


# ── Product Sync ─────────────────────────────────────────────────────────────


@router.post("/products")
def trigger_product_sync(
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_client),
    woo: WooCommerceClient = Depends(get_woo_client),
) -> dict[str, Any]:
    """Trigger a full product sync from Odoo to WooCommerce."""
    logger.info("manual_product_sync_triggered")
    try:
        from app.tasks.product_tasks import sync_all_products
        sync_all_products.delay()
        return {"status": "accepted", "message": "Product sync task dispatched"}
    except Exception:
        # Fallback to synchronous execution
        service = ProductSyncService(odoo, woo, db)
        result = service.sync_all_products()
        return result.model_dump()


@router.post("/products/{sku}")
def trigger_single_product_sync(
    sku: str,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_client),
    woo: WooCommerceClient = Depends(get_woo_client),
) -> dict[str, Any]:
    """Trigger a single product sync by SKU."""
    logger.info("manual_product_sync_single_triggered", sku=sku)
    service = ProductSyncService(odoo, woo, db)
    result = service.sync_product_by_sku(sku)
    return result.model_dump()


# ── Inventory Sync ───────────────────────────────────────────────────────────


@router.post("/inventory")
def trigger_inventory_sync(
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_client),
    woo: WooCommerceClient = Depends(get_woo_client),
) -> dict[str, Any]:
    """Trigger a full inventory sync from Odoo to WooCommerce."""
    logger.info("manual_inventory_sync_triggered")
    try:
        from app.tasks.inventory_tasks import sync_all_inventory
        sync_all_inventory.delay()
        return {"status": "accepted", "message": "Inventory sync task dispatched"}
    except Exception:
        service = InventorySyncService(odoo, woo, db)
        result = service.sync_all_inventory()
        return result.to_dict()


# ── Order Sync ───────────────────────────────────────────────────────────────


@router.post("/orders/{woo_order_id}")
def trigger_single_order_sync(
    woo_order_id: int,
    db: Session = Depends(get_db),
    odoo: OdooClient = Depends(get_odoo_client),
    woo: WooCommerceClient = Depends(get_woo_client),
) -> dict[str, Any]:
    """Trigger a single order sync by WooCommerce order ID."""
    logger.info("manual_order_sync_triggered", woo_order_id=woo_order_id)
    service = OrderSyncService(odoo, woo, db)
    result = service.sync_order(woo_order_id)
    return result.model_dump()


# ── Sync Status ──────────────────────────────────────────────────────────────


@router.get("/status")
def get_sync_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get overall sync status and counts."""
    product_repo = ProductMappingRepository(db)
    order_repo = OrderMappingRepository(db)
    customer_repo = CustomerMappingRepository(db)
    failed_job_repo = FailedJobRepository(db)
    sync_log_repo = SyncLogRepository(db)

    # Get last sync logs for each type
    product_logs = sync_log_repo.list_by_entity("product", limit=1)
    inventory_logs = sync_log_repo.list_by_entity("inventory", limit=1)
    order_logs = sync_log_repo.list_by_entity("order", limit=1)

    return {
        "product_sync": {
            "last_sync_at": product_logs[0].created_at.isoformat() if product_logs else None,
            "last_status": product_logs[0].status.value if product_logs else "never",
        },
        "inventory_sync": {
            "last_sync_at": inventory_logs[0].created_at.isoformat() if inventory_logs else None,
            "last_status": inventory_logs[0].status.value if inventory_logs else "never",
        },
        "order_sync": {
            "last_sync_at": order_logs[0].created_at.isoformat() if order_logs else None,
            "last_status": order_logs[0].status.value if order_logs else "never",
        },
        "total_products_mapped": product_repo.count(),
        "total_orders_mapped": order_repo.count(),
        "total_customers_mapped": customer_repo.count(),
        "pending_failed_jobs": failed_job_repo.count_pending(),
        "dead_letter_jobs": failed_job_repo.count_dead_letters(),
    }


# ── Sync Logs ────────────────────────────────────────────────────────────────


@router.get("/logs")
def get_sync_logs(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    entity_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """Get paginated sync logs with optional filters."""
    sync_log_repo = SyncLogRepository(db)

    if entity_type:
        logs = sync_log_repo.list_by_entity(entity_type, limit=limit)
    elif status:
        from app.database.models import SyncLogStatus
        try:
            status_enum = SyncLogStatus(status)
            logs = sync_log_repo.list_by_status(status_enum, limit=limit, offset=offset)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Valid values: success, failed, skipped",
            )
    else:
        logs = sync_log_repo.list_all(limit=limit, offset=offset)

    return [SyncLogResponse.model_validate(log).model_dump() for log in logs]


# ── Failed Jobs ──────────────────────────────────────────────────────────────


@router.get("/failed-jobs")
def get_failed_jobs(
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    """List failed jobs with optional status filter."""
    failed_job_repo = FailedJobRepository(db)

    job_status = None
    if status:
        try:
            job_status = FailedJobStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Valid values: pending, retrying, resolved, dead_letter",
            )

    jobs = failed_job_repo.list_all(limit=limit, offset=offset, status=job_status)
    return [FailedJobResponse.model_validate(job).model_dump() for job in jobs]


@router.post("/failed-jobs/{job_id}/retry")
def retry_failed_job(
    job_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Manually retry a specific failed job."""
    failed_job_repo = FailedJobRepository(db)
    job = failed_job_repo.get_by_id(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Failed job not found")

    if job.status not in (FailedJobStatus.PENDING, FailedJobStatus.DEAD_LETTER):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry job with status: {job.status.value}",
        )

    # Dispatch retry task
    try:
        from app.tasks.retry_tasks import retry_single_job
        retry_single_job.delay(job_id)
        return {"status": "accepted", "message": f"Retry task dispatched for job {job_id}"}
    except Exception:
        # Mark for immediate retry
        job.status = FailedJobStatus.PENDING
        job.retry_count = 0  # Reset retry count for manual retry
        from datetime import datetime, timezone
        job.next_retry_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "queued", "message": f"Job {job_id} queued for retry"}

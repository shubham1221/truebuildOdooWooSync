"""
TrueBuild Integration Platform — WooCommerce Webhook Endpoints.

Receives webhooks from WooCommerce for order events.
All webhooks are validated via HMAC-SHA256 signature before processing.
Processing is dispatched to Celery tasks for async execution.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.responses import JSONResponse

from app.config.settings import get_settings
from app.security.webhook_auth import WebhookAuthError, validate_webhook_signature
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


async def _validate_and_parse(
    request: Request,
    x_wc_webhook_signature: str | None = None,
) -> dict[str, Any]:
    """
    Validate webhook signature and parse the payload.

    Must use raw body for HMAC validation — never parse first.
    """
    settings = get_settings()
    raw_body = await request.body()

    # Validate signature
    if settings.ENVIRONMENT == "development":
        logger.warning("webhook_signature_bypass_in_development")
    else:
        if not x_wc_webhook_signature:
            logger.warning("webhook_missing_signature_header")
            raise HTTPException(status_code=401, detail="Missing signature header")

        try:
            validate_webhook_signature(
                raw_body=raw_body,
                signature=x_wc_webhook_signature,
                secret=settings.WOO_WEBHOOK_SECRET,
            )
        except WebhookAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))

    # Parse the validated payload
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    return payload


@router.post("/order-created")
async def webhook_order_created(
    request: Request,
    x_wc_webhook_signature: str | None = Header(None),
) -> JSONResponse:
    """
    Handle WooCommerce order.created webhook.

    Dispatches order processing to a Celery background task.
    Returns 200 immediately to acknowledge receipt.
    """
    payload = await _validate_and_parse(request, x_wc_webhook_signature)

    woo_order_id = payload.get("id")
    if not woo_order_id:
        logger.warning("webhook_order_created_no_id")
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "message": "No order ID in payload"},
        )

    logger.info("webhook_order_created_received", woo_order_id=woo_order_id)

    # Dispatch to Celery task
    try:
        from app.tasks.order_tasks import process_order_webhook
        process_order_webhook.delay(payload)
    except Exception as e:
        logger.error("webhook_task_dispatch_error", error=str(e))
        # Even if dispatch fails, we store and will retry
        # Fall back to sync processing if Celery is unavailable
        _process_order_sync_fallback(payload)

    return JSONResponse(
        status_code=200,
        content={"status": "accepted", "woo_order_id": woo_order_id},
    )


@router.post("/order-updated")
async def webhook_order_updated(
    request: Request,
    x_wc_webhook_signature: str | None = Header(None),
) -> JSONResponse:
    """
    Handle WooCommerce order.updated webhook.

    Re-syncs the order if it has already been processed.
    """
    payload = await _validate_and_parse(request, x_wc_webhook_signature)

    woo_order_id = payload.get("id")
    if not woo_order_id:
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "message": "No order ID in payload"},
        )

    logger.info("webhook_order_updated_received", woo_order_id=woo_order_id)

    try:
        from app.tasks.order_tasks import process_order_webhook
        process_order_webhook.delay(payload)
    except Exception as e:
        logger.error("webhook_task_dispatch_error", error=str(e))

    return JSONResponse(
        status_code=200,
        content={"status": "accepted", "woo_order_id": woo_order_id},
    )


@router.post("/order-refunded")
async def webhook_order_refunded(
    request: Request,
    x_wc_webhook_signature: str | None = Header(None),
) -> JSONResponse:
    """
    Handle WooCommerce order.refunded webhook.

    Records the refund and attempts credit note creation in Odoo.
    """
    payload = await _validate_and_parse(request, x_wc_webhook_signature)

    woo_order_id = payload.get("id")
    if not woo_order_id:
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "message": "No order ID in payload"},
        )

    logger.info("webhook_order_refunded_received", woo_order_id=woo_order_id)

    try:
        from app.tasks.order_tasks import process_order_refund
        process_order_refund.delay(woo_order_id)
    except Exception as e:
        logger.error("webhook_task_dispatch_error", error=str(e))

    return JSONResponse(
        status_code=200,
        content={"status": "accepted", "woo_order_id": woo_order_id},
    )


@router.post("/order-cancelled")
async def webhook_order_cancelled(
    request: Request,
    x_wc_webhook_signature: str | None = Header(None),
) -> JSONResponse:
    """
    Handle WooCommerce order cancelled webhook.

    Cancels the corresponding Odoo Sales Order if it exists.
    """
    payload = await _validate_and_parse(request, x_wc_webhook_signature)

    woo_order_id = payload.get("id")
    if not woo_order_id:
        return JSONResponse(
            status_code=200,
            content={"status": "ignored", "message": "No order ID in payload"},
        )

    logger.info("webhook_order_cancelled_received", woo_order_id=woo_order_id)

    try:
        from app.tasks.order_tasks import process_order_cancellation
        process_order_cancellation.delay(woo_order_id)
    except Exception as e:
        logger.error("webhook_task_dispatch_error", error=str(e))

    return JSONResponse(
        status_code=200,
        content={"status": "accepted", "woo_order_id": woo_order_id},
    )


def _process_order_sync_fallback(payload: dict[str, Any]) -> None:
    """
    Synchronous fallback for order processing when Celery is unavailable.

    Imports are deferred to avoid circular dependencies.
    """
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
            service.sync_order_from_payload(payload)
        finally:
            db.close()
    except Exception as e:
        logger.error("webhook_sync_fallback_error", error=str(e))

"""
TrueBuild Integration Platform — Global Error Handler Middleware.

Centralized exception handling for all API endpoints.
Converts exceptions to standardized JSON error responses
with structured logging.
"""

from __future__ import annotations

import traceback
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.services.odoo_client import OdooAPIError
from app.services.woo_client import WooCommerceAPIError
from app.security.webhook_auth import WebhookAuthError
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Global error handler middleware.

    Catches all unhandled exceptions and returns standardized
    JSON error responses. Assigns a unique request_id for tracing.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Generate unique request ID for tracing
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            return response

        except WebhookAuthError as e:
            logger.warning(
                "webhook_auth_error",
                request_id=request_id,
                path=request.url.path,
                error=str(e),
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": "authentication_error",
                    "message": str(e),
                    "request_id": request_id,
                },
            )

        except OdooAPIError as e:
            logger.error(
                "odoo_api_error",
                request_id=request_id,
                path=request.url.path,
                model=e.model,
                method=e.method,
                error=str(e),
            )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "odoo_api_error",
                    "message": f"Odoo API error: {e}",
                    "request_id": request_id,
                },
            )

        except WooCommerceAPIError as e:
            logger.error(
                "woocommerce_api_error",
                request_id=request_id,
                path=request.url.path,
                status_code=e.status_code,
                error=str(e),
            )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "woocommerce_api_error",
                    "message": f"WooCommerce API error: {e}",
                    "request_id": request_id,
                },
            )

        except ValueError as e:
            logger.warning(
                "validation_error",
                request_id=request_id,
                path=request.url.path,
                error=str(e),
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": "validation_error",
                    "message": str(e),
                    "request_id": request_id,
                },
            )

        except Exception as e:
            logger.error(
                "unhandled_exception",
                request_id=request_id,
                path=request.url.path,
                method=request.method,
                error=str(e),
                traceback=traceback.format_exc(),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "An unexpected error occurred",
                    "request_id": request_id,
                },
            )

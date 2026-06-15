"""
TrueBuild Integration Platform — FastAPI Application Entry Point.

Production-grade FastAPI application with middleware stack,
structured logging, CORS, and API routing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import get_settings
from app.utils.logging import setup_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler — startup and shutdown events."""
    settings = get_settings()

    # Configure structured logging
    setup_logging(
        log_level=settings.LOG_LEVEL,
        environment=settings.ENVIRONMENT,
    )

    logger = get_logger(__name__)
    logger.info(
        "application_starting",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
    )

    # Initialize database engine (ensures pool is ready)
    from app.database.db import get_engine
    get_engine()
    logger.info("database_pool_initialized")

    yield

    # Shutdown
    logger.info("application_shutting_down")


def create_app() -> FastAPI:
    """
    FastAPI application factory.

    Creates and configures the FastAPI application with all middleware,
    routers, and settings.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "WooCommerce ↔ Odoo Online Integration Platform for TrueBuild Deck & Turf. "
            "Synchronizes products, orders, inventory, and customers between "
            "Odoo (master) and WooCommerce (sales channel)."
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS Middleware ──────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Custom Middleware ────────────────────────────────────────────
    # Note: Middleware is applied in reverse order (last added = first executed)
    from app.middleware.error_handler import ErrorHandlerMiddleware
    from app.middleware.rate_limiter import RateLimiterMiddleware

    app.add_middleware(RateLimiterMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # ── API Routers ──────────────────────────────────────────────────
    from app.api.router import api_router
    app.include_router(api_router)

    return app


# Create application instance
app = create_app()

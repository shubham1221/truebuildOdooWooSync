"""
TrueBuild Integration Platform — API Router.

Assembles all API sub-routers into a single application router.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.sync_endpoints import router as sync_router
from app.api.webhooks import router as webhook_router

api_router = APIRouter()

# Include all sub-routers
api_router.include_router(health_router)
api_router.include_router(webhook_router)
api_router.include_router(sync_router)

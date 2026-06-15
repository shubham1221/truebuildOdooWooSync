"""
TrueBuild Integration Platform — Celery Application Configuration.

Configures Celery with Redis broker, beat schedule for periodic tasks,
and task routing for product sync, order sync, and inventory sync.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config.settings import get_settings

settings = get_settings()

# Create Celery application
celery_app = Celery(
    "truebuild",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,

    # Result backend
    result_expires=3600,  # Results expire after 1 hour

    # Task discovery
    include=[
        "app.tasks.product_tasks",
        "app.tasks.order_tasks",
        "app.tasks.inventory_tasks",
        "app.tasks.retry_tasks",
    ],

    # Beat schedule for periodic tasks
    beat_schedule={
        "sync-products-every-5-minutes": {
            "task": "app.tasks.product_tasks.sync_all_products",
            "schedule": settings.PRODUCT_SYNC_INTERVAL_SECONDS,
            "options": {"expires": settings.PRODUCT_SYNC_INTERVAL_SECONDS},
        },
        "sync-inventory-every-5-minutes": {
            "task": "app.tasks.inventory_tasks.sync_all_inventory",
            "schedule": settings.INVENTORY_SYNC_INTERVAL_SECONDS,
            "options": {"expires": settings.INVENTORY_SYNC_INTERVAL_SECONDS},
        },
        "process-retry-queue-every-minute": {
            "task": "app.tasks.retry_tasks.process_retry_queue",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
    },

    # Task routes
    task_routes={
        "app.tasks.product_tasks.*": {"queue": "product_sync"},
        "app.tasks.order_tasks.*": {"queue": "order_sync"},
        "app.tasks.inventory_tasks.*": {"queue": "inventory_sync"},
        "app.tasks.retry_tasks.*": {"queue": "retry"},
    },

    # Default queue
    task_default_queue="default",
)

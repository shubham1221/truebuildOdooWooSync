#!/usr/bin/env python3
"""
TrueBuild Integration Platform — CLI Management Tool.

Usage:
    python manage.py migrate         — Run Alembic database migrations
    python manage.py sync-products   — Trigger full product sync
    python manage.py sync-inventory  — Trigger full inventory sync
    python manage.py sync-order <id> — Sync a single WooCommerce order
    python manage.py retry-failed    — Retry all failed jobs
    python manage.py health          — Check all system connections
    python manage.py init-db         — Create all database tables
    python manage.py create-project  — Create project folder structure
"""

from __future__ import annotations

import sys
import json


def cmd_migrate() -> None:
    """Run Alembic database migrations."""
    import subprocess
    result = subprocess.run(["alembic", "upgrade", "head"], check=True)
    sys.exit(result.returncode)


def cmd_init_db() -> None:
    """Create all database tables (development only)."""
    from app.config.settings import get_settings
    from app.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

    from app.database.db import create_all_tables
    # Force model import so all tables are registered
    from app.database import models  # noqa: F401
    create_all_tables()
    print("✓ All database tables created successfully.")


def cmd_sync_products() -> None:
    """Trigger full product sync."""
    from app.config.settings import get_settings
    from app.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

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
        print(f"\n✓ Product Sync Complete:")
        print(f"  Total:   {result.total_products}")
        print(f"  Created: {result.created}")
        print(f"  Updated: {result.updated}")
        print(f"  Skipped: {result.skipped}")
        print(f"  Failed:  {result.failed}")
        print(f"  Time:    {result.duration_seconds}s")
    finally:
        db.close()


def cmd_sync_inventory() -> None:
    """Trigger full inventory sync."""
    from app.config.settings import get_settings
    from app.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

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
        print(f"\n✓ Inventory Sync Complete:")
        print(f"  Total:   {result.total_products}")
        print(f"  Updated: {result.updated}")
        print(f"  Failed:  {result.failed}")
        print(f"  Time:    {result.duration_seconds}s")
    finally:
        db.close()


def cmd_sync_order(woo_order_id: int) -> None:
    """Sync a single WooCommerce order."""
    from app.config.settings import get_settings
    from app.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

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
        result = service.sync_order(woo_order_id)
        print(f"\n✓ Order Sync Result:")
        print(f"  WooCommerce Order: {result.woo_order_id}")
        print(f"  Odoo Order:        {result.odoo_order_id}")
        print(f"  Action:            {result.action}")
        print(f"  Message:           {result.message}")
    finally:
        db.close()


def cmd_retry_failed() -> None:
    """Retry all pending failed jobs."""
    from app.config.settings import get_settings
    from app.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

    from app.database.db import get_session_factory
    from app.repositories.failed_job_repo import FailedJobRepository

    session_factory = get_session_factory()
    db = session_factory()
    try:
        repo = FailedJobRepository(db)
        ready = repo.get_ready_for_retry()
        print(f"\n  Found {len(ready)} jobs ready for retry.")
        if ready:
            from app.tasks.retry_tasks import _execute_retry
            for job in ready:
                try:
                    _execute_retry(job, db)
                    repo.mark_resolved(job)
                    print(f"  ✓ Job {job.id} ({job.job_type}) — resolved")
                except Exception as e:
                    repo.increment_retry(job, str(e), settings.RETRY_DELAYS_SECONDS)
                    print(f"  ✗ Job {job.id} ({job.job_type}) — failed: {e}")
            db.commit()
        print("\n✓ Retry processing complete.")
    finally:
        db.close()


def cmd_health() -> None:
    """Check all system connections."""
    from app.config.settings import get_settings
    from app.utils.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.ENVIRONMENT)

    print(f"\n  TrueBuild Integration Platform v{settings.APP_VERSION}")
    print(f"  Environment: {settings.ENVIRONMENT}\n")

    # Database
    try:
        from app.database.db import get_engine
        from sqlalchemy import text
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("  ✓ PostgreSQL — Connected")
    except Exception as e:
        print(f"  ✗ PostgreSQL — Error: {e}")

    # Redis
    try:
        import redis
        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        print("  ✓ Redis — Connected")
    except Exception as e:
        print(f"  ✗ Redis — Error: {e}")

    # Odoo
    try:
        from app.services.odoo_client import OdooClient
        odoo = OdooClient()
        result = odoo.check_connection()
        if result["status"] == "connected":
            print(f"  ✓ Odoo — Connected (v{result.get('server_version', '?')})")
        else:
            print(f"  ✗ Odoo — {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"  ✗ Odoo — Error: {e}")

    # WooCommerce
    try:
        from app.services.woo_client import WooCommerceClient
        woo = WooCommerceClient()
        result = woo.check_connection()
        if result["status"] == "connected":
            print(f"  ✓ WooCommerce — Connected (v{result.get('wc_version', '?')})")
        else:
            print(f"  ✗ WooCommerce — {result.get('error', 'Unknown error')}")
    except Exception as e:
        print(f"  ✗ WooCommerce — Error: {e}")

    print()


def cmd_create_project() -> None:
    """Create the full project folder structure."""
    from pathlib import Path

    folders = [
        "app", "app/api", "app/config", "app/database", "app/middleware",
        "app/models", "app/repositories", "app/schemas", "app/security",
        "app/services", "app/tasks", "app/utils",
        "tests", "logs", "nginx", "alembic/versions",
    ]
    for folder in folders:
        Path(folder).mkdir(parents=True, exist_ok=True)
    print("✓ Project folder structure created.")


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    commands = {
        "migrate": cmd_migrate,
        "init-db": cmd_init_db,
        "sync-products": cmd_sync_products,
        "sync-inventory": cmd_sync_inventory,
        "retry-failed": cmd_retry_failed,
        "health": cmd_health,
        "create-project": cmd_create_project,
    }

    if command == "sync-order":
        if len(sys.argv) < 3:
            print("Usage: python manage.py sync-order <woo_order_id>")
            sys.exit(1)
        cmd_sync_order(int(sys.argv[2]))
    elif command in commands:
        commands[command]()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
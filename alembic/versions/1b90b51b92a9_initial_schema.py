"""Initial schema

Revision ID: 1b90b51b92a9
Revises:
Create Date: 2026-06-15 11:33:57.383679
"""

from typing import Sequence, Union

from alembic import op


revision: str = '1b90b51b92a9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL throughout so this migration is fully idempotent.
    # PostgreSQL has no CREATE TYPE IF NOT EXISTS, so we use the DO block pattern.
    # Tables use CREATE TABLE IF NOT EXISTS so re-runs are always safe.

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE sync_status_enum AS ENUM ('pending', 'synced', 'failed', 'skipped');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE order_status_enum AS ENUM ('pending', 'synced', 'failed', 'cancelled', 'refunded');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE sync_log_status_enum AS ENUM ('success', 'failed', 'skipped');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE failed_job_status_enum AS ENUM ('pending', 'retrying', 'resolved', 'dead_letter');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    # ── product_mappings ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS product_mappings (
            id              SERIAL PRIMARY KEY,
            odoo_product_id INTEGER NOT NULL UNIQUE,
            woo_product_id  INTEGER UNIQUE,
            sku             VARCHAR(255) NOT NULL UNIQUE,
            product_type    VARCHAR(50)  NOT NULL DEFAULT 'simple',
            sync_status     sync_status_enum NOT NULL DEFAULT 'pending',
            last_sync_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_mappings_odoo_product_id ON product_mappings (odoo_product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_mappings_woo_product_id  ON product_mappings (woo_product_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_product_mappings_sku             ON product_mappings (sku)")

    # ── variant_mappings ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS variant_mappings (
            id                 SERIAL PRIMARY KEY,
            product_mapping_id INTEGER NOT NULL REFERENCES product_mappings(id) ON DELETE CASCADE,
            odoo_variant_id    INTEGER NOT NULL UNIQUE,
            woo_variant_id     INTEGER UNIQUE,
            sku                VARCHAR(255) NOT NULL UNIQUE,
            sync_status        sync_status_enum NOT NULL DEFAULT 'pending',
            last_sync_at       TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_variant_mappings_product_mapping_id ON variant_mappings (product_mapping_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_variant_mappings_odoo_variant_id    ON variant_mappings (odoo_variant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_variant_mappings_woo_variant_id     ON variant_mappings (woo_variant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_variant_mappings_sku                ON variant_mappings (sku)")

    # ── customer_mappings ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS customer_mappings (
            id              SERIAL PRIMARY KEY,
            odoo_partner_id INTEGER NOT NULL UNIQUE,
            woo_customer_id INTEGER,
            email           VARCHAR(255) NOT NULL UNIQUE,
            first_name      VARCHAR(255),
            last_name       VARCHAR(255),
            last_sync_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_customer_mappings_odoo_partner_id ON customer_mappings (odoo_partner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_customer_mappings_woo_customer_id ON customer_mappings (woo_customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_customer_mappings_email           ON customer_mappings (email)")

    # ── order_mappings ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_mappings (
            id              SERIAL PRIMARY KEY,
            woo_order_id    INTEGER NOT NULL UNIQUE,
            odoo_order_id   INTEGER UNIQUE,
            order_number    VARCHAR(100),
            odoo_invoice_id INTEGER,
            status          order_status_enum NOT NULL DEFAULT 'pending',
            total_amount    VARCHAR(20),
            currency        VARCHAR(10) DEFAULT 'AUD',
            last_sync_at    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_order_mappings_woo_order_id  ON order_mappings (woo_order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_order_mappings_odoo_order_id ON order_mappings (odoo_order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_order_mappings_order_number  ON order_mappings (order_number)")

    # ── sync_logs ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_logs (
            id          SERIAL PRIMARY KEY,
            event_type  VARCHAR(100) NOT NULL,
            entity_type VARCHAR(50)  NOT NULL,
            entity_id   VARCHAR(100),
            direction   VARCHAR(20)  NOT NULL DEFAULT 'odoo_to_woo',
            status      sync_log_status_enum NOT NULL DEFAULT 'success',
            message     TEXT,
            payload     JSON,
            duration_ms INTEGER,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sync_logs_entity     ON sync_logs (entity_type, entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sync_logs_created_at ON sync_logs (created_at)")

    # ── failed_jobs ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS failed_jobs (
            id               SERIAL PRIMARY KEY,
            job_type         VARCHAR(100) NOT NULL,
            entity_type      VARCHAR(50),
            entity_id        VARCHAR(100),
            payload          JSON,
            error_message    TEXT,
            error_traceback  TEXT,
            retry_count      INTEGER NOT NULL DEFAULT 0,
            max_retries      INTEGER NOT NULL DEFAULT 4,
            next_retry_at    TIMESTAMPTZ,
            status           failed_job_status_enum NOT NULL DEFAULT 'pending',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            resolved_at      TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_failed_jobs_retry ON failed_jobs (next_retry_at, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS failed_jobs")
    op.execute("DROP TABLE IF EXISTS sync_logs")
    op.execute("DROP TABLE IF EXISTS order_mappings")
    op.execute("DROP TABLE IF EXISTS customer_mappings")
    op.execute("DROP TABLE IF EXISTS variant_mappings")
    op.execute("DROP TABLE IF EXISTS product_mappings")
    op.execute("DROP TYPE IF EXISTS failed_job_status_enum")
    op.execute("DROP TYPE IF EXISTS sync_log_status_enum")
    op.execute("DROP TYPE IF EXISTS order_status_enum")
    op.execute("DROP TYPE IF EXISTS sync_status_enum")

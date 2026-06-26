"""Initial schema

Revision ID: 1b90b51b92a9
Revises:
Create Date: 2026-06-15 11:33:57.383679
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '1b90b51b92a9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types (PostgreSQL requires explicit type creation)
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
    op.create_table(
        'product_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('odoo_product_id', sa.Integer(), nullable=False),
        sa.Column('woo_product_id', sa.Integer(), nullable=True),
        sa.Column('sku', sa.String(255), nullable=False),
        sa.Column('product_type', sa.String(50), nullable=False, server_default='simple'),
        sa.Column('sync_status', sa.Enum('pending', 'synced', 'failed', 'skipped', name='sync_status_enum', create_type=False), nullable=False, server_default='pending'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('odoo_product_id'),
        sa.UniqueConstraint('woo_product_id'),
        sa.UniqueConstraint('sku'),
    )
    op.create_index('ix_product_mappings_odoo_product_id', 'product_mappings', ['odoo_product_id'])
    op.create_index('ix_product_mappings_woo_product_id', 'product_mappings', ['woo_product_id'])
    op.create_index('ix_product_mappings_sku', 'product_mappings', ['sku'])

    # ── variant_mappings ─────────────────────────────────────────────────
    op.create_table(
        'variant_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('product_mapping_id', sa.Integer(), nullable=False),
        sa.Column('odoo_variant_id', sa.Integer(), nullable=False),
        sa.Column('woo_variant_id', sa.Integer(), nullable=True),
        sa.Column('sku', sa.String(255), nullable=False),
        sa.Column('sync_status', sa.Enum('pending', 'synced', 'failed', 'skipped', name='sync_status_enum', create_type=False), nullable=False, server_default='pending'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_mapping_id'], ['product_mappings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('odoo_variant_id'),
        sa.UniqueConstraint('woo_variant_id'),
        sa.UniqueConstraint('sku'),
    )
    op.create_index('ix_variant_mappings_product_mapping_id', 'variant_mappings', ['product_mapping_id'])
    op.create_index('ix_variant_mappings_odoo_variant_id', 'variant_mappings', ['odoo_variant_id'])
    op.create_index('ix_variant_mappings_woo_variant_id', 'variant_mappings', ['woo_variant_id'])
    op.create_index('ix_variant_mappings_sku', 'variant_mappings', ['sku'])

    # ── customer_mappings ────────────────────────────────────────────────
    op.create_table(
        'customer_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('odoo_partner_id', sa.Integer(), nullable=False),
        sa.Column('woo_customer_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(255), nullable=True),
        sa.Column('last_name', sa.String(255), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('odoo_partner_id'),
        sa.UniqueConstraint('email'),
    )
    op.create_index('ix_customer_mappings_odoo_partner_id', 'customer_mappings', ['odoo_partner_id'])
    op.create_index('ix_customer_mappings_woo_customer_id', 'customer_mappings', ['woo_customer_id'])
    op.create_index('ix_customer_mappings_email', 'customer_mappings', ['email'])

    # ── order_mappings ───────────────────────────────────────────────────
    op.create_table(
        'order_mappings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('woo_order_id', sa.Integer(), nullable=False),
        sa.Column('odoo_order_id', sa.Integer(), nullable=True),
        sa.Column('order_number', sa.String(100), nullable=True),
        sa.Column('odoo_invoice_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('pending', 'synced', 'failed', 'cancelled', 'refunded', name='order_status_enum', create_type=False), nullable=False, server_default='pending'),
        sa.Column('total_amount', sa.String(20), nullable=True),
        sa.Column('currency', sa.String(10), nullable=True, server_default='AUD'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('woo_order_id'),
        sa.UniqueConstraint('odoo_order_id'),
    )
    op.create_index('ix_order_mappings_woo_order_id', 'order_mappings', ['woo_order_id'])
    op.create_index('ix_order_mappings_odoo_order_id', 'order_mappings', ['odoo_order_id'])
    op.create_index('ix_order_mappings_order_number', 'order_mappings', ['order_number'])

    # ── sync_logs ────────────────────────────────────────────────────────
    op.create_table(
        'sync_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=False),
        sa.Column('entity_id', sa.String(100), nullable=True),
        sa.Column('direction', sa.String(20), nullable=False, server_default='odoo_to_woo'),
        sa.Column('status', sa.Enum('success', 'failed', 'skipped', name='sync_log_status_enum', create_type=False), nullable=False, server_default='success'),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('payload', sa.dialects.postgresql.JSON(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sync_logs_entity', 'sync_logs', ['entity_type', 'entity_id'])
    op.create_index('ix_sync_logs_created_at', 'sync_logs', ['created_at'])

    # ── failed_jobs ──────────────────────────────────────────────────────
    op.create_table(
        'failed_jobs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('job_type', sa.String(100), nullable=False),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', sa.String(100), nullable=True),
        sa.Column('payload', sa.dialects.postgresql.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('error_traceback', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Enum('pending', 'retrying', 'resolved', 'dead_letter', name='failed_job_status_enum', create_type=False), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_failed_jobs_retry', 'failed_jobs', ['next_retry_at', 'status'])


def downgrade() -> None:
    op.drop_index('ix_failed_jobs_retry', table_name='failed_jobs')
    op.drop_table('failed_jobs')

    op.drop_index('ix_sync_logs_created_at', table_name='sync_logs')
    op.drop_index('ix_sync_logs_entity', table_name='sync_logs')
    op.drop_table('sync_logs')

    op.drop_index('ix_order_mappings_order_number', table_name='order_mappings')
    op.drop_index('ix_order_mappings_odoo_order_id', table_name='order_mappings')
    op.drop_index('ix_order_mappings_woo_order_id', table_name='order_mappings')
    op.drop_table('order_mappings')

    op.drop_index('ix_customer_mappings_email', table_name='customer_mappings')
    op.drop_index('ix_customer_mappings_woo_customer_id', table_name='customer_mappings')
    op.drop_index('ix_customer_mappings_odoo_partner_id', table_name='customer_mappings')
    op.drop_table('customer_mappings')

    op.drop_index('ix_variant_mappings_sku', table_name='variant_mappings')
    op.drop_index('ix_variant_mappings_woo_variant_id', table_name='variant_mappings')
    op.drop_index('ix_variant_mappings_odoo_variant_id', table_name='variant_mappings')
    op.drop_index('ix_variant_mappings_product_mapping_id', table_name='variant_mappings')
    op.drop_table('variant_mappings')

    op.drop_index('ix_product_mappings_sku', table_name='product_mappings')
    op.drop_index('ix_product_mappings_woo_product_id', table_name='product_mappings')
    op.drop_index('ix_product_mappings_odoo_product_id', table_name='product_mappings')
    op.drop_table('product_mappings')

    op.execute("DROP TYPE IF EXISTS failed_job_status_enum")
    op.execute("DROP TYPE IF EXISTS sync_log_status_enum")
    op.execute("DROP TYPE IF EXISTS order_status_enum")
    op.execute("DROP TYPE IF EXISTS sync_status_enum")

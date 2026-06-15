"""
TrueBuild — Repository Unit Tests.

Tests CRUD operations for all 6 repository classes.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.database.models import (
    CustomerMapping,
    FailedJob,
    FailedJobStatus,
    OrderMapping,
    OrderStatus,
    ProductMapping,
    SyncLog,
    SyncLogStatus,
    SyncStatus,
    VariantMapping,
)
from app.repositories.customer_repo import CustomerMappingRepository
from app.repositories.failed_job_repo import FailedJobRepository
from app.repositories.order_repo import OrderMappingRepository
from app.repositories.product_repo import ProductMappingRepository
from app.repositories.sync_log_repo import SyncLogRepository
from app.repositories.variant_repo import VariantMappingRepository


class TestProductMappingRepository:
    """Tests for ProductMappingRepository."""

    def test_create(self, db_session: Session):
        repo = ProductMappingRepository(db_session)
        mapping = repo.create(odoo_product_id=1, sku="TEST-001")
        assert mapping.id is not None
        assert mapping.sku == "TEST-001"
        assert mapping.sync_status == SyncStatus.PENDING

    def test_get_by_sku(self, db_session: Session):
        repo = ProductMappingRepository(db_session)
        repo.create(odoo_product_id=2, sku="FIND-ME")
        found = repo.get_by_sku("FIND-ME")
        assert found is not None
        assert found.sku == "FIND-ME"

    def test_get_by_sku_not_found(self, db_session: Session):
        repo = ProductMappingRepository(db_session)
        found = repo.get_by_sku("NONEXISTENT")
        assert found is None

    def test_mark_synced(self, db_session: Session):
        repo = ProductMappingRepository(db_session)
        mapping = repo.create(odoo_product_id=3, sku="SYNC-001")
        repo.mark_synced(mapping, woo_product_id=500)
        assert mapping.sync_status == SyncStatus.SYNCED
        assert mapping.woo_product_id == 500

    def test_mark_failed(self, db_session: Session):
        repo = ProductMappingRepository(db_session)
        mapping = repo.create(odoo_product_id=4, sku="FAIL-001")
        repo.mark_failed(mapping)
        assert mapping.sync_status == SyncStatus.FAILED

    def test_count(self, db_session: Session):
        repo = ProductMappingRepository(db_session)
        initial_count = repo.count()
        repo.create(odoo_product_id=5, sku="COUNT-001")
        repo.create(odoo_product_id=6, sku="COUNT-002")
        assert repo.count() == initial_count + 2


class TestVariantMappingRepository:
    """Tests for VariantMappingRepository."""

    def test_create_and_list_by_product(self, db_session: Session):
        product_repo = ProductMappingRepository(db_session)
        product = product_repo.create(odoo_product_id=10, sku="VAR-PARENT")

        variant_repo = VariantMappingRepository(db_session)
        variant_repo.create(product_mapping_id=product.id, odoo_variant_id=100, sku="VAR-001")
        variant_repo.create(product_mapping_id=product.id, odoo_variant_id=101, sku="VAR-002")

        variants = variant_repo.list_by_product(product.id)
        assert len(variants) == 2

    def test_get_by_sku(self, db_session: Session):
        product_repo = ProductMappingRepository(db_session)
        product = product_repo.create(odoo_product_id=11, sku="VAR-PARENT-2")

        variant_repo = VariantMappingRepository(db_session)
        variant_repo.create(product_mapping_id=product.id, odoo_variant_id=102, sku="FIND-VAR")

        found = variant_repo.get_by_sku("FIND-VAR")
        assert found is not None
        assert found.odoo_variant_id == 102


class TestCustomerMappingRepository:
    """Tests for CustomerMappingRepository."""

    def test_create(self, db_session: Session):
        repo = CustomerMappingRepository(db_session)
        mapping = repo.create(odoo_partner_id=1, email="test@example.com")
        assert mapping.email == "test@example.com"

    def test_get_by_email_case_insensitive(self, db_session: Session):
        repo = CustomerMappingRepository(db_session)
        repo.create(odoo_partner_id=2, email="User@Example.COM")
        found = repo.get_by_email("user@example.com")
        assert found is not None

    def test_get_by_email_not_found(self, db_session: Session):
        repo = CustomerMappingRepository(db_session)
        found = repo.get_by_email("nobody@example.com")
        assert found is None


class TestOrderMappingRepository:
    """Tests for OrderMappingRepository."""

    def test_create(self, db_session: Session):
        repo = OrderMappingRepository(db_session)
        mapping = repo.create(woo_order_id=5001, order_number="5001")
        assert mapping.woo_order_id == 5001
        assert mapping.status == OrderStatus.PENDING

    def test_mark_synced(self, db_session: Session):
        repo = OrderMappingRepository(db_session)
        mapping = repo.create(woo_order_id=5002)
        repo.mark_synced(mapping, odoo_order_id=100, odoo_invoice_id=200)
        assert mapping.status == OrderStatus.SYNCED
        assert mapping.odoo_order_id == 100
        assert mapping.odoo_invoice_id == 200

    def test_get_by_woo_id(self, db_session: Session):
        repo = OrderMappingRepository(db_session)
        repo.create(woo_order_id=5003, order_number="5003")
        found = repo.get_by_woo_id(5003)
        assert found is not None
        assert found.order_number == "5003"


class TestSyncLogRepository:
    """Tests for SyncLogRepository."""

    def test_log_success(self, db_session: Session):
        repo = SyncLogRepository(db_session)
        log = repo.log_success(
            event_type="product_sync",
            entity_type="product",
            entity_id="SKU-001",
            message="Synced successfully",
        )
        assert log.status == SyncLogStatus.SUCCESS
        assert log.entity_id == "SKU-001"

    def test_log_failure(self, db_session: Session):
        repo = SyncLogRepository(db_session)
        log = repo.log_failure(
            event_type="order_sync",
            entity_type="order",
            entity_id="5001",
            message="Connection error",
        )
        assert log.status == SyncLogStatus.FAILED

    def test_list_by_entity(self, db_session: Session):
        repo = SyncLogRepository(db_session)
        repo.log_success("test", "product", "SKU-X")
        repo.log_success("test", "product", "SKU-X")
        repo.log_success("test", "order", "O-1")

        product_logs = repo.list_by_entity("product", "SKU-X")
        assert len(product_logs) == 2


class TestFailedJobRepository:
    """Tests for FailedJobRepository."""

    def test_create(self, db_session: Session):
        repo = FailedJobRepository(db_session)
        job = repo.create(
            job_type="product_sync",
            error_message="Test error",
            entity_type="product",
            entity_id="SKU-FAIL",
        )
        assert job.retry_count == 0
        assert job.status == FailedJobStatus.PENDING
        assert job.next_retry_at is not None

    def test_increment_retry_to_dead_letter(self, db_session: Session):
        repo = FailedJobRepository(db_session)
        job = repo.create(
            job_type="order_sync",
            error_message="Persistent failure",
            max_retries=2,
        )

        # Retry 1
        repo.increment_retry(job, retry_delays=[60, 300])
        assert job.retry_count == 1
        assert job.status == FailedJobStatus.PENDING

        # Retry 2 → dead letter
        repo.increment_retry(job, retry_delays=[60, 300])
        assert job.retry_count == 2
        assert job.status == FailedJobStatus.DEAD_LETTER
        assert job.resolved_at is not None

    def test_mark_resolved(self, db_session: Session):
        repo = FailedJobRepository(db_session)
        job = repo.create(job_type="test", error_message="Error")
        repo.mark_resolved(job)
        assert job.status == FailedJobStatus.RESOLVED

    def test_count_pending(self, db_session: Session):
        repo = FailedJobRepository(db_session)
        initial = repo.count_pending()
        repo.create(job_type="test1", error_message="err")
        repo.create(job_type="test2", error_message="err")
        assert repo.count_pending() == initial + 2

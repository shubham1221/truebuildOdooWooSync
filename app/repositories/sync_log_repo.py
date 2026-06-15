"""
TrueBuild Integration Platform — Sync Log Repository.

CRUD operations for SyncLog audit records.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.models import SyncLog, SyncLogStatus
from app.utils.logging import get_logger

logger = get_logger(__name__)


class SyncLogRepository:
    """Repository for SyncLog CRUD operations."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str | None = None,
        direction: str = "odoo_to_woo",
        status: SyncLogStatus = SyncLogStatus.SUCCESS,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> SyncLog:
        """Create a new sync log entry."""
        log_entry = SyncLog(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            direction=direction,
            status=status,
            message=message,
            payload=payload,
            duration_ms=duration_ms,
        )
        self.db.add(log_entry)
        self.db.flush()
        return log_entry

    def log_success(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str | None = None,
        direction: str = "odoo_to_woo",
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> SyncLog:
        """Convenience: create a success log entry."""
        return self.create(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            direction=direction,
            status=SyncLogStatus.SUCCESS,
            message=message,
            payload=payload,
            duration_ms=duration_ms,
        )

    def log_failure(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str | None = None,
        direction: str = "odoo_to_woo",
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> SyncLog:
        """Convenience: create a failure log entry."""
        return self.create(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            direction=direction,
            status=SyncLogStatus.FAILED,
            message=message,
            payload=payload,
            duration_ms=duration_ms,
        )

    def get_by_id(self, log_id: int) -> SyncLog | None:
        """Get a sync log by primary key."""
        return self.db.get(SyncLog, log_id)

    def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[SyncLog]:
        """List all sync logs, most recent first."""
        stmt = (
            select(SyncLog)
            .order_by(SyncLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return self.db.execute(stmt).scalars().all()

    def list_by_entity(
        self,
        entity_type: str,
        entity_id: str | None = None,
        limit: int = 50,
    ) -> Sequence[SyncLog]:
        """List sync logs for a specific entity."""
        stmt = select(SyncLog).where(SyncLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(SyncLog.entity_id == entity_id)
        stmt = stmt.order_by(SyncLog.created_at.desc()).limit(limit)
        return self.db.execute(stmt).scalars().all()

    def list_by_status(
        self,
        status: SyncLogStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[SyncLog]:
        """List sync logs filtered by status."""
        stmt = (
            select(SyncLog)
            .where(SyncLog.status == status)
            .order_by(SyncLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return self.db.execute(stmt).scalars().all()

    def list_since(self, since: datetime, limit: int = 500) -> Sequence[SyncLog]:
        """List sync logs since a given timestamp."""
        stmt = (
            select(SyncLog)
            .where(SyncLog.created_at >= since)
            .order_by(SyncLog.created_at.desc())
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def count(self) -> int:
        """Count total sync log entries."""
        stmt = select(func.count(SyncLog.id))
        return self.db.execute(stmt).scalar() or 0

    def count_by_status(self, status: SyncLogStatus) -> int:
        """Count sync logs by status."""
        stmt = select(func.count(SyncLog.id)).where(SyncLog.status == status)
        return self.db.execute(stmt).scalar() or 0

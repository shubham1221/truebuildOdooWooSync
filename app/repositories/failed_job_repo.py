"""
TrueBuild Integration Platform — Failed Job Repository.

CRUD operations for FailedJob records (dead letter queue).
"""

from __future__ import annotations

import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import FailedJob, FailedJobStatus
from app.utils.logging import get_logger

logger = get_logger(__name__)


class FailedJobRepository:
    """Repository for FailedJob CRUD operations."""

    # Default retry delays: 1min, 5min, 15min, 1hr
    DEFAULT_RETRY_DELAYS = [60, 300, 900, 3600]

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        job_type: str,
        error_message: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
        max_retries: int = 4,
        retry_delays: list[int] | None = None,
    ) -> FailedJob:
        """
        Create a new failed job entry with the first retry scheduled.

        Args:
            job_type: Type of job (e.g., product_sync, order_sync)
            error_message: Human-readable error description
            entity_type: Entity type (product, order, etc.)
            entity_id: Entity identifier (SKU, order ID)
            payload: Original job payload for retry
            max_retries: Maximum retry attempts
            retry_delays: Custom retry delay schedule in seconds
        """
        delays = retry_delays or self.DEFAULT_RETRY_DELAYS
        now = datetime.now(timezone.utc)
        first_delay = delays[0] if delays else 60

        job = FailedJob(
            job_type=job_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            error_message=error_message,
            error_traceback=traceback.format_exc(),
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=now + timedelta(seconds=first_delay),
            status=FailedJobStatus.PENDING,
        )
        self.db.add(job)
        self.db.flush()
        logger.warning(
            "failed_job_created",
            job_type=job_type,
            entity_type=entity_type,
            entity_id=entity_id,
            error=error_message,
            next_retry_at=job.next_retry_at.isoformat(),
        )
        return job

    def get_by_id(self, job_id: int) -> FailedJob | None:
        """Get a failed job by primary key."""
        return self.db.get(FailedJob, job_id)

    def get_ready_for_retry(self, limit: int = 20) -> Sequence[FailedJob]:
        """
        Get all jobs ready to be retried.

        Returns jobs where:
        - next_retry_at <= now
        - status is PENDING
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(FailedJob)
            .where(
                FailedJob.status == FailedJobStatus.PENDING,
                FailedJob.next_retry_at <= now,
            )
            .order_by(FailedJob.next_retry_at)
            .limit(limit)
        )
        return self.db.execute(stmt).scalars().all()

    def increment_retry(
        self,
        job: FailedJob,
        error_message: str | None = None,
        retry_delays: list[int] | None = None,
    ) -> FailedJob:
        """
        Increment retry count and schedule next retry.

        If max retries exceeded, move to dead letter.
        """
        delays = retry_delays or self.DEFAULT_RETRY_DELAYS
        job.retry_count += 1

        if error_message:
            job.error_message = error_message
            job.error_traceback = traceback.format_exc()

        if job.retry_count >= job.max_retries:
            # Move to dead letter queue
            job.status = FailedJobStatus.DEAD_LETTER
            job.next_retry_at = None
            job.resolved_at = datetime.now(timezone.utc)
            logger.error(
                "job_moved_to_dead_letter",
                job_id=job.id,
                job_type=job.job_type,
                entity_id=job.entity_id,
                retry_count=job.retry_count,
            )
        else:
            # Schedule next retry with exponential backoff
            delay_idx = min(job.retry_count, len(delays) - 1)
            delay = delays[delay_idx]
            job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            job.status = FailedJobStatus.PENDING
            logger.info(
                "job_retry_scheduled",
                job_id=job.id,
                job_type=job.job_type,
                retry_count=job.retry_count,
                next_retry_at=job.next_retry_at.isoformat(),
            )

        self.db.flush()
        return job

    def mark_resolved(self, job: FailedJob) -> FailedJob:
        """Mark a failed job as resolved (successfully retried)."""
        job.status = FailedJobStatus.RESOLVED
        job.resolved_at = datetime.now(timezone.utc)
        job.next_retry_at = None
        self.db.flush()
        logger.info("failed_job_resolved", job_id=job.id, job_type=job.job_type)
        return job

    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        status: FailedJobStatus | None = None,
    ) -> Sequence[FailedJob]:
        """List failed jobs with optional status filter."""
        stmt = select(FailedJob).order_by(FailedJob.created_at.desc())
        if status is not None:
            stmt = stmt.where(FailedJob.status == status)
        stmt = stmt.limit(limit).offset(offset)
        return self.db.execute(stmt).scalars().all()

    def list_dead_letters(self, limit: int = 100) -> Sequence[FailedJob]:
        """List all dead letter jobs."""
        return self.list_all(limit=limit, status=FailedJobStatus.DEAD_LETTER)

    def delete(self, job: FailedJob) -> None:
        """Delete a failed job record."""
        self.db.delete(job)
        self.db.flush()

    def count_pending(self) -> int:
        """Count pending failed jobs."""
        from sqlalchemy import func

        stmt = select(func.count(FailedJob.id)).where(
            FailedJob.status == FailedJobStatus.PENDING
        )
        return self.db.execute(stmt).scalar() or 0

    def count_dead_letters(self) -> int:
        """Count dead letter jobs."""
        from sqlalchemy import func

        stmt = select(func.count(FailedJob.id)).where(
            FailedJob.status == FailedJobStatus.DEAD_LETTER
        )
        return self.db.execute(stmt).scalar() or 0

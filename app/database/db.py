"""
TrueBuild Integration Platform — Database Engine & Session.

Provides SQLAlchemy engine, session factory, and FastAPI dependency
for database session injection.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config.settings import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Declarative base for all ORM models
Base = declarative_base()

# Module-level engine and session factory (initialized lazily)
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create the SQLAlchemy engine singleton."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.DATABASE_URL,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_pre_ping=True,  # Verify connections before use
            echo=settings.DB_ECHO,
        )

        # Log connection events in debug mode
        @event.listens_for(_engine, "connect")
        def _on_connect(dbapi_conn: Any, connection_record: Any) -> None:
            logger.debug("database_connection_opened")

        logger.info(
            "database_engine_created",
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
    return _engine


def get_session_factory() -> sessionmaker:
    """Get or create the session factory singleton."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.

    Yields a SQLAlchemy session and ensures it is closed after use.
    Usage:
        @app.get("/example")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_all_tables() -> None:
    """Create all tables defined by ORM models. Used for testing."""
    Base.metadata.create_all(bind=get_engine())


def drop_all_tables() -> None:
    """Drop all tables. Used for testing only."""
    Base.metadata.drop_all(bind=get_engine())

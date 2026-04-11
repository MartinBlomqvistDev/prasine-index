"""Async PostgreSQL connection layer for the Prasine Index pipeline.

Owns the SQLAlchemy async engine, session factory, and declarative base used by
all ORM models. The pgvector extension is enabled at startup and the Vector
column type is registered with asyncpg so that embedding operations work
transparently through the ORM. All database I/O across the pipeline flows
through get_session().
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from pgvector.sqlalchemy import Vector
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from core.logger import get_logger

__all__ = [
    "Base",
    "Vector",
    "get_engine",
    "get_session",
    "healthcheck",
    "init_db",
    "teardown_db",
]

load_dotenv()

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------

# DATABASE_URL must use the asyncpg driver scheme:
#   postgresql+asyncpg://user:password@host:port/dbname
_DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://prasine:prasine@localhost:5432/prasine_index",
)

# Pool sizing: 5 base connections, up to 10 overflow. Overflow connections are
# returned immediately when released rather than being held open. This is suitable
# for both the async pipeline and the FastAPI process; adjust via environment
# variables for production deployments with higher concurrency.
_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "5"))
_MAX_OVERFLOW: int = int(os.environ.get("DB_MAX_OVERFLOW", "10"))
_POOL_TIMEOUT: int = int(os.environ.get("DB_POOL_TIMEOUT", "30"))

# NullPool is used in test environments (detected via TESTING=true) to prevent
# connection pool state from leaking across test cases.
_TESTING: bool = os.environ.get("TESTING", "false").lower() == "true"

_engine: AsyncEngine | None = None


def _build_engine() -> AsyncEngine:
    """Construct the SQLAlchemy async engine with appropriate pool settings.

    Uses NullPool when TESTING=true so that test cases that call teardown_db()
    can fully dispose of all connections without pool interference.

    Returns:
        A configured :py:class:`sqlalchemy.ext.asyncio.AsyncEngine` instance.
    """
    pool_kwargs: dict[str, Any] = (
        {"poolclass": NullPool}
        if _TESTING
        else {
            "pool_size": _POOL_SIZE,
            "max_overflow": _MAX_OVERFLOW,
            "pool_timeout": _POOL_TIMEOUT,
            "pool_pre_ping": True,
            "pool_recycle": 1800,  # recycle connections after 30 minutes
        }
    )
    engine = create_async_engine(
        _DATABASE_URL,
        echo=os.environ.get("DB_ECHO", "false").lower() == "true",
        **pool_kwargs,
    )
    _register_pgvector_codec(engine)
    return engine


def _register_pgvector_codec(engine: AsyncEngine) -> None:
    """Register the pgvector asyncpg codec on every new connection.

    asyncpg does not automatically know how to serialise and deserialise the
    PostgreSQL ``vector`` type. The ``pgvector.asyncpg`` codec must be registered
    on the raw asyncpg connection object, which SQLAlchemy exposes via the
    ``connect`` event on the sync-level driver connection.

    Args:
        engine: The async engine whose connection pool will have the codec
            registered on each new connection checkout.
    """
    try:
        import pgvector.asyncpg as pgvector_asyncpg

        @event.listens_for(engine.sync_engine, "connect")
        def _on_connect(dbapi_connection: Any, _connection_record: Any) -> None:
            """Register the pgvector codec on the raw asyncpg connection.

            Args:
                dbapi_connection: The raw asyncpg connection wrapper provided
                    by SQLAlchemy's asyncpg dialect.
                _connection_record: SQLAlchemy connection record (unused).
            """

            async def _register(conn: Any) -> None:
                try:
                    await pgvector_asyncpg.register_vector(conn)
                except ValueError:
                    # Supabase installs pgvector in the 'extensions' schema.
                    # If that also fails, the extension is simply not installed.
                    with contextlib.suppress(ValueError):
                        await pgvector_asyncpg.register_vector(conn, schema="extensions")

            dbapi_connection.run_async(_register)

    except ImportError:
        logger.warning(
            "pgvector.asyncpg not available; vector operations will not function. "
            "Install with: pip install pgvector",
            extra={"operation": "pgvector_codec_registration_skipped"},
        )


def get_engine() -> AsyncEngine:
    """Return the process-wide async engine, creating it on first call.

    The engine is a module-level singleton. Calling this function multiple
    times returns the same instance. Use :py:func:`teardown_db` to dispose
    of the engine and its connection pool.

    Returns:
        The singleton :py:class:`~sqlalchemy.ext.asyncio.AsyncEngine`.
    """
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the current engine.

    Returns:
        An :py:class:`~sqlalchemy.ext.asyncio.async_sessionmaker` instance.
    """
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a database session with automatic cleanup.

    Commits the transaction on clean exit and rolls back on any exception,
    ensuring the connection is always returned to the pool in a clean state.
    Sessions are not shared across concurrent pipeline runs; each agent call
    that needs database access should open its own session.

    Yields:
        An :py:class:`~sqlalchemy.ext.asyncio.AsyncSession` ready for use.

    Raises:
        Re-raises any exception after rolling back the transaction.

    Example::

        from core.database import get_session

        async with get_session() as session:
            result = await session.execute(select(Claim).where(Claim.id == claim_id))
            claim = result.scalar_one_or_none()
    """
    factory = _get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared declarative base for all Prasine Index ORM models.

    All SQLAlchemy ORM table classes must inherit from this base so that
    :py:func:`init_db` can discover them via ``Base.metadata.create_all``.

    Import this class alongside the ORM model definition::

        from core.database import Base

        class ClaimRow(Base):
            __tablename__ = "claims"
            ...
    """


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """Initialise the database schema on application startup.

    Performs three operations in order:

    1. Enables the ``vector`` PostgreSQL extension (requires PostgreSQL 15+
       with pgvector installed; no-op if already enabled).
    2. Enables the ``uuid-ossp`` extension for server-side UUID generation
       in raw SQL statements.
    3. Creates all tables registered with :py:class:`Base` that do not yet
       exist. This is an additive operation and will never drop or alter
       existing tables — schema migrations are managed separately via Alembic.

    This function is idempotent and safe to call on every application startup.

    Raises:
        sqlalchemy.exc.OperationalError: If the database is unreachable or
            the current user lacks CREATE EXTENSION privileges.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await _enable_extensions(conn)
        await _create_schema(conn)
    logger.info(
        "Database schema initialised",
        extra={"operation": "db_init_complete"},
    )


async def _enable_extensions(conn: AsyncConnection) -> None:
    """Enable required PostgreSQL extensions if not already active.

    Args:
        conn: An open async connection within a transaction.
    """
    for extension in ("vector", "uuid-ossp"):
        await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{extension}"'))
        logger.info(
            f"PostgreSQL extension enabled: {extension}",
            extra={"operation": "pg_extension_enabled", "error_type": None},
        )


async def _create_schema(conn: AsyncConnection) -> None:
    """Create all Prasine Index tables if they do not already exist.

    All statements use ``CREATE TABLE IF NOT EXISTS`` so the function is
    idempotent and safe to call on every startup. No existing data is
    modified or dropped.

    Args:
        conn: An open async connection within a transaction.
    """
    statements = [
        # Companies — stable EU company registry data
        """
        CREATE TABLE IF NOT EXISTS companies (
            id                       UUID PRIMARY KEY,
            name                     TEXT NOT NULL,
            lei                      TEXT,
            isin                     TEXT,
            ticker                   TEXT,
            country                  TEXT NOT NULL,
            sector                   TEXT NOT NULL,
            sub_sector               TEXT,
            eu_ets_installation_ids  JSONB NOT NULL DEFAULT '[]',
            transparency_register_id TEXT,
            ir_page_url              TEXT,
            csrd_reporting           BOOLEAN NOT NULL DEFAULT FALSE,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Claims — atomic unit of work: one row per extracted green claim
        """
        CREATE TABLE IF NOT EXISTS claims (
            id                      UUID PRIMARY KEY,
            trace_id                UUID NOT NULL,
            company_id              UUID NOT NULL REFERENCES companies(id),
            source_url              TEXT NOT NULL,
            source_type             TEXT NOT NULL,
            raw_text                TEXT NOT NULL,
            normalised_text         TEXT,
            claim_category          TEXT NOT NULL,
            page_reference          TEXT,
            publication_date        TIMESTAMPTZ,
            detected_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status                  TEXT NOT NULL DEFAULT 'DETECTED',
            is_repeat               BOOLEAN NOT NULL DEFAULT FALSE,
            previous_claim_id       UUID,
            modified_after_scoring  BOOLEAN NOT NULL DEFAULT FALSE,
            original_scored_text    TEXT,
            embedding               vector(1536)
        )
        """,
        # Claim lifecycle — immutable status transition log
        """
        CREATE TABLE IF NOT EXISTS claim_lifecycle (
            id               UUID PRIMARY KEY,
            claim_id         UUID NOT NULL REFERENCES claims(id),
            from_status      TEXT,
            to_status        TEXT NOT NULL,
            transitioned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            transitioned_by  TEXT NOT NULL
        )
        """,
        # Greenwashing scores — Judge Agent verdicts
        """
        CREATE TABLE IF NOT EXISTS greenwashing_scores (
            id              UUID PRIMARY KEY,
            claim_id        UUID NOT NULL REFERENCES claims(id),
            company_id      UUID NOT NULL REFERENCES companies(id),
            trace_id        UUID NOT NULL,
            score           FLOAT NOT NULL,
            score_breakdown JSONB NOT NULL DEFAULT '{}',
            verdict         TEXT NOT NULL,
            reasoning       TEXT NOT NULL,
            confidence      FLOAT NOT NULL,
            scored_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            judge_model_id  TEXT NOT NULL
        )
        """,
        # Reports — publication-ready Markdown output
        """
        CREATE TABLE IF NOT EXISTS reports (
            claim_id         UUID PRIMARY KEY REFERENCES claims(id),
            trace_id         UUID NOT NULL,
            report_markdown  TEXT NOT NULL,
            published_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        # Trace log — structured execution log per agent step
        """
        CREATE TABLE IF NOT EXISTS trace_log (
            id            UUID PRIMARY KEY,
            trace_id      UUID NOT NULL,
            claim_id      UUID,
            agent         TEXT NOT NULL,
            outcome       TEXT NOT NULL,
            started_at    TIMESTAMPTZ NOT NULL,
            completed_at  TIMESTAMPTZ,
            duration_ms   INTEGER,
            input_schema  TEXT NOT NULL,
            output_schema TEXT,
            error_type    TEXT,
            error_message TEXT,
            retry_count   INTEGER NOT NULL DEFAULT 0,
            llm_model_id  TEXT,
            tokens_used   INTEGER,
            metadata      JSONB NOT NULL DEFAULT '{}'
        )
        """,
        # Discovery state — content hash per monitored URL for change detection
        """
        CREATE TABLE IF NOT EXISTS discovery_state (
            source_url      TEXT PRIMARY KEY,
            content_hash    TEXT NOT NULL,
            last_checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    ]
    for stmt in statements:
        await conn.execute(text(stmt))

    # Enable Row-Level Security on every table. This blocks anonymous access
    # via the Supabase PostgREST REST API (anon key) while leaving direct
    # database connections (postgres superuser) and service-role API calls
    # completely unaffected — both bypass RLS by design.
    # ALTER TABLE ... ENABLE ROW LEVEL SECURITY is idempotent.
    rls_tables = [
        "companies",
        "claims",
        "claim_lifecycle",
        "greenwashing_scores",
        "reports",
        "trace_log",
        "discovery_state",
    ]
    for table in rls_tables:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))


async def teardown_db() -> None:
    """Dispose of the engine and its connection pool.

    Should be called during application shutdown (e.g. in FastAPI's
    ``lifespan`` shutdown handler) and in test teardown to ensure all
    connections are cleanly closed.

    Subsequent calls to :py:func:`get_engine` or :py:func:`get_session`
    after ``teardown_db`` will create a new engine instance.
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info(
            "Database engine disposed",
            extra={"operation": "db_teardown_complete"},
        )


async def healthcheck() -> dict[str, str]:
    """Execute a minimal query to verify database connectivity.

    Intended for use in the FastAPI ``/health`` endpoint and pre-flight
    checks in the pipeline. Returns a status dict rather than raising, so
    the caller can decide how to surface connectivity failures.

    Returns:
        A dict with keys ``"status"`` (``"ok"`` or ``"error"``) and
        ``"detail"`` (empty string on success, error message on failure).

    Example::

        from core.database import healthcheck

        status = await healthcheck()
        if status["status"] != "ok":
            logger.error("Database unreachable", extra={"error_type": status["detail"]})
    """
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok", "detail": ""}
    except Exception as exc:
        logger.error(
            "Database healthcheck failed",
            exc_info=True,
            extra={"operation": "db_healthcheck", "error_type": type(exc).__name__},
        )
        return {"status": "error", "detail": str(exc)}

# Root pytest configuration for the Prasine Index test suite. Declares shared
# fixtures available across all test modules without explicit import. The database
# fixtures use NullPool (via TESTING=true env var) and connect to a dedicated
# test database to ensure test isolation from any running development instance.

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

# Set TESTING=true before any database module is imported, so that NullPool
# is used for all connections created during the test session.
os.environ.setdefault("TESTING", "true")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://prasine:prasine@localhost:5432/prasine_index_test",
)


# ---------------------------------------------------------------------------
# Domain model fixtures — zero external dependencies, used by all unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def company_id() -> uuid.UUID:
    """Fixed company UUID for use across tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def trace_id() -> uuid.UUID:
    """Fixed trace UUID for use across tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def claim_id() -> uuid.UUID:
    """Fixed claim UUID for use across tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000003")


@pytest.fixture
def utc_now() -> datetime:
    """Current UTC-aware datetime snapshot for use in tests."""
    return datetime.now(UTC)

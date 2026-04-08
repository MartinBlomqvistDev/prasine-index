"""One-shot migration: enable Row-Level Security on all Prasine Index tables.

Supabase exposes every table via its PostgREST REST API. Without RLS, any
client with the project URL and the anonymous key can read, write, and delete
all data. Enabling RLS with no anon/authenticated policies blocks all public
API access while leaving direct database connections (postgres superuser) and
service-role API calls unaffected — both bypass RLS by design.

This script is idempotent. Re-running it is safe.

Usage:
    python scripts/enable_rls.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from core.database import get_session

_TABLES = [
    "companies",
    "claims",
    "claim_lifecycle",
    "greenwashing_scores",
    "reports",
    "trace_log",
    "discovery_state",
]


async def enable_rls() -> None:
    async with get_session() as session:
        for table in _TABLES:
            await session.execute(
                text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            )
            print(f"  RLS enabled: {table}")
    print(f"\nDone — RLS enabled on {len(_TABLES)} tables.")
    print(
        "Anonymous PostgREST access is now blocked. "
        "Backend connections (postgres / service_role) are unaffected."
    )


if __name__ == "__main__":
    asyncio.run(enable_rls())

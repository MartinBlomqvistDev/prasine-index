"""Seed the published index companies with their country, sector and EU ETS installations.

The assessment runner inserts an unknown company with placeholder values
(country "EU", sector "Corporate", no installations), so without this seed the
judge is told nothing about a company's EU ETS installations and the reports
state a mapping gap. This script derives the installations from the EUTL
snapshot in EUTL24/ and writes them for the eight index companies.

Attribution is conservative, because a wrong mapping publishes an untrue
statement about a named company:

- An installation counts when its account holder's name matches the company
  on whole words, or when the company's own website lists it as an operation
  (``verified_installations``).
- Holders that only share a word with the company are excluded by name, for
  example Aker BP ASA, which is a separate company.
- Installations in the UK registry are excluded: the UK left the EU ETS after
  2020, and a series that stops then would read as a fall in emissions.
- Maritime operators are excluded: shipping entered the EU ETS in 2024, and a
  series that starts then would read as a rise.
- Only installations with verified emissions in 2019 or later are kept, so the
  judge sees the installations relevant to current claims.

Usage:
    python scripts/seed_index_companies.py           # print the mapping only
    python scripts/seed_index_companies.py --apply   # write it to the database
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_EUTL_DIR = Path(__file__).parent.parent / "EUTL24"
_OPERATORS = _EUTL_DIR / "operators_daily.csv"
_YEARLY = _EUTL_DIR / "operators_yearly_activity_daily.csv"

_MIN_RECENT_YEAR = 2019
_EXCLUDED_REGISTRIES = frozenset({"GB"})
_EXCLUDED_ACTIVITY = "maritime"


@dataclass(frozen=True)
class _IndexCompany:
    name: str
    country: str
    sector: str
    holder_patterns: tuple[str, ...] = ()
    excluded_holders: tuple[str, ...] = ()
    verified_installations: tuple[str, ...] = field(default=())


INDEX_COMPANIES: tuple[_IndexCompany, ...] = (
    _IndexCompany("Ryanair Holdings plc", "IE", "Aviation", (r"\bryanair\b",)),
    _IndexCompany(
        "Glencore plc",
        "CH",
        "Mining",
        (r"\bglencore\b",),
        # Listed as Glencore operations on glencore.com (checked 2026-11-02):
        # Portovesme, the San Juan de Nieva zinc plant of Asturiana de Zinc,
        # and the Nordenham zinc smelter.
        verified_installations=("IT_205605", "ES_882", "DE_203844"),
    ),
    _IndexCompany("BP plc", "GB", "Oil & Gas", (r"\bbp\b",), excluded_holders=(r"\baker bp\b",)),
    _IndexCompany("Enel SpA", "IT", "Utilities", (r"\benel\b",)),
    _IndexCompany("IKEA Group", "NL", "Retail", (r"\bikea\b",)),
    _IndexCompany("H&M Group", "SE", "Retail", (r"\bh\s*&\s*m\b", r"\bhennes\b")),
    _IndexCompany("SSAB AB", "SE", "Steel", (r"\bssab\b",)),
    _IndexCompany(
        "Ørsted A/S", "DK", "Utilities", (r"\børsted\b", r"\borsted\b", r"\bdong energy\b")
    ),
)


def _company_id(name: str) -> uuid.UUID:
    """Return the deterministic company id the assessment runner uses."""
    return uuid.uuid5(uuid.NAMESPACE_DNS, name.lower())


def _latest_years() -> dict[str, int]:
    """Map 'REGISTRY_ID' to the latest year with verified emissions."""
    latest: dict[str, int] = {}
    with _YEARLY.open(encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            try:
                if float(row["VERIFIED_EMISSIONS"]) < 0:
                    continue
                year = int(row["PERIOD_YEAR"])
            except ValueError:
                continue
            key = f"{row['REGISTRY_CODE'].strip().upper()}_{row['INSTALLATION_IDENTIFIER']}"
            latest[key] = max(year, latest.get(key, 0))
    return latest


def build_mapping() -> dict[str, list[str]]:
    """Return the EU ETS installation ids for each index company."""
    latest = _latest_years()
    with _OPERATORS.open(encoding="utf-8", errors="replace") as fh:
        operators = list(csv.DictReader(fh))

    mapping: dict[str, list[str]] = {}
    for company in INDEX_COMPANIES:
        ids: set[str] = set(company.verified_installations)
        for row in operators:
            holder = (row["ACCOUNT_HOLDER_NAME"] or "").lower()
            if not any(re.search(p, holder) for p in company.holder_patterns):
                continue
            if any(re.search(p, holder) for p in company.excluded_holders):
                continue
            registry = row["REGISTRY_CODE"].strip().upper()
            if registry in _EXCLUDED_REGISTRIES:
                continue
            if _EXCLUDED_ACTIVITY in (row["ACTIVITY_TYPE"] or "").lower():
                continue
            ids.add(f"{registry}_{row['INSTALLATION_IDENTIFIER']}")
        mapping[company.name] = sorted(i for i in ids if latest.get(i, 0) >= _MIN_RECENT_YEAR)
    return mapping


async def _apply(mapping: dict[str, list[str]]) -> None:
    from sqlalchemy import text

    from core.database import get_session, init_db, teardown_db

    await init_db()
    try:
        async with get_session() as session:
            for company in INDEX_COMPANIES:
                await session.execute(
                    text("""
                        INSERT INTO companies (id, name, country, sector, eu_ets_installation_ids)
                        VALUES (:id, :name, :country, :sector, CAST(:ids AS JSONB))
                        ON CONFLICT (id) DO UPDATE SET
                            country = EXCLUDED.country,
                            sector = EXCLUDED.sector,
                            eu_ets_installation_ids = EXCLUDED.eu_ets_installation_ids,
                            updated_at = NOW()
                    """),
                    {
                        "id": str(_company_id(company.name)),
                        "name": company.name,
                        "country": company.country,
                        "sector": company.sector,
                        "ids": json.dumps(mapping[company.name]),
                    },
                )
            await session.commit()
    finally:
        await teardown_db()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Write the mapping to the database.")
    args = parser.parse_args()

    mapping = build_mapping()
    for name, ids in mapping.items():
        print(f"{name}: {len(ids)} installation(s) {ids}")

    if args.apply:
        asyncio.run(_apply(mapping))
        print("Written to the companies table.")


if __name__ == "__main__":
    main()

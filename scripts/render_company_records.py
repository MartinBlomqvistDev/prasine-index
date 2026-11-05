"""Rebuild the Company Record section of published reports from current data.

The company record is built in code from records that describe a company as a
whole, with no model involved, so it can be rebuilt without running an
assessment again after a change to how the record is written. Each company is
looked up the way the pipeline looks it up, by name, with its EU ETS
installations read from the database.

Never use it to bring a published report's data up to date: the claims in the
report were judged on the data of their run, and a record rebuilt from newer
data would disagree with the evidence beside it (a newer TPI assessment in the
record, an older one in the evidence). Refresh data by running the assessment
again.

Usage:
    python scripts/render_company_records.py "Ryanair Holdings plc" "BP plc"
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text  # noqa: E402

from core.company_record import render_company_record  # noqa: E402
from core.database import get_session, init_db, teardown_db  # noqa: E402
from ingest.ca100 import fetch_ca100_data  # noqa: E402
from ingest.coal_exit import fetch_coal_exit_data  # noqa: E402
from ingest.egt import fetch_egt_data  # noqa: E402
from ingest.enforcement import fetch_enforcement_data  # noqa: E402
from ingest.eu_ets import fetch_eu_ets_data  # noqa: E402
from ingest.fossil_finance import fetch_fossil_finance_data  # noqa: E402
from ingest.gcpt import fetch_gcpt_data  # noqa: E402
from ingest.gogel import fetch_gogel_data  # noqa: E402
from ingest.goget import fetch_goget_data  # noqa: E402
from ingest.lobby_map import fetch_lobby_map_data  # noqa: E402
from ingest.sbti import fetch_sbti_data  # noqa: E402
from ingest.tpi import fetch_tpi_data  # noqa: E402
from models.claim import Claim, ClaimCategory, SourceType  # noqa: E402
from models.evidence import Evidence  # noqa: E402

_REPORTS_DIR = Path(__file__).parent.parent / "docs" / "reports"

_FETCHERS = (
    fetch_lobby_map_data,
    fetch_gogel_data,
    fetch_coal_exit_data,
    fetch_goget_data,
    fetch_gcpt_data,
    fetch_egt_data,
    fetch_sbti_data,
    fetch_ca100_data,
    fetch_tpi_data,
    fetch_enforcement_data,
    fetch_fossil_finance_data,
)


def _slug(name: str) -> str:
    sys.path.insert(0, str(Path(__file__).parent))
    from run_assessment import _slug as slug

    return slug(name)


async def _company(name: str) -> SimpleNamespace:
    company_id = uuid.uuid5(uuid.NAMESPACE_DNS, name.lower())
    async with get_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT name, country, sector, eu_ets_installation_ids "
                    "FROM companies WHERE id = :id"
                ),
                {"id": str(company_id)},
            )
        ).first()
    if row is None:
        raise SystemExit(f"{name}: not in the companies table")
    return SimpleNamespace(
        id=company_id,
        name=row.name,
        country=row.country,
        sector=row.sector,
        eu_ets_installation_ids=list(row.eu_ets_installation_ids or []),
    )


async def _evidence(company: SimpleNamespace) -> list[Evidence]:
    claim = Claim(
        trace_id=uuid.uuid4(),
        company_id=company.id,
        source_url="https://www.prasineindex.com",
        source_type=SourceType.WEBSITE,
        raw_text="Company record",
        claim_category=ClaimCategory.OTHER,
    )
    # The fetchers read only the name and country, which the namespace carries.
    results = await asyncio.gather(
        *(fetch(claim=claim, company=cast("Any", company)) for fetch in _FETCHERS)
    )
    evidence = [record for batch in results for record in batch]
    if company.eu_ets_installation_ids:
        evidence += await fetch_eu_ets_data(
            claim=claim, installation_ids=company.eu_ets_installation_ids
        )
    return evidence


def _replace_section(markdown: str, body: str) -> str:
    """Put the company record into a canonical report, replacing any earlier one."""
    heading = "\n### Company Record\n"
    start = markdown.find(heading)
    if start != -1:
        end = markdown.find("\n---\n", start + len(heading))
        return f"{markdown[:start]}{heading}\n{body}\n{markdown[end:]}"
    anchor = markdown.find("\n---\n")
    return f"{markdown[:anchor]}\n{heading}\n{body}\n{markdown[anchor:]}"


async def main(names: list[str]) -> None:
    await init_db()
    try:
        for name in names:
            path = _REPORTS_DIR / f"{_slug(name)}.md"
            company = await _company(name)
            body = render_company_record(await _evidence(company))
            path.write_text(
                _replace_section(path.read_text(encoding="utf-8"), body), encoding="utf-8"
            )
            print(f"{name}: company record written to {path.name}")
    finally:
        await teardown_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("companies", nargs="+", help="Company names, as used for the assessment")
    asyncio.run(main(parser.parse_args().companies))

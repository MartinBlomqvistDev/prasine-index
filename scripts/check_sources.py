"""Check every data source for a company before an assessment, without calling a model.

Runs each verification fetcher except the source document step (the only one that
calls a model) for the company as it is stored in the database, and prints what each
source returns: how many records, which entity it matched and the start of its
summary. It also fetches the entry page and reports its HTTP status and the
sustainability report it links to. Nothing is written and no tokens are spent.

Usage:
    python scripts/check_sources.py "BP plc=https://www.bp.com/..." "SSAB AB=https://..."
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
load_dotenv(Path(__file__).parent.parent / ".env")

from sqlalchemy import text  # noqa: E402

from core.database import get_session, init_db, teardown_db  # noqa: E402
from ingest.ca100 import fetch_ca100_data  # noqa: E402
from ingest.cdp import fetch_cdp_data  # noqa: E402
from ingest.climate_trace import fetch_climate_trace_data  # noqa: E402
from ingest.coal_exit import fetch_coal_exit_data  # noqa: E402
from ingest.edgar import fetch_edgar_data  # noqa: E402
from ingest.eea_national import fetch_eea_national_data  # noqa: E402
from ingest.egt import fetch_egt_data  # noqa: E402
from ingest.enforcement import fetch_enforcement_data  # noqa: E402
from ingest.eprtr import fetch_eprtr_data  # noqa: E402
from ingest.eu_ets import fetch_eu_ets_data  # noqa: E402
from ingest.eu_innovation_fund import fetch_eu_innovation_fund_data  # noqa: E402
from ingest.eu_transparency_register import fetch_eu_transparency_register_data  # noqa: E402
from ingest.eurlex import fetch_eurlex_data  # noqa: E402
from ingest.eurostat import fetch_eurostat_data  # noqa: E402
from ingest.fossil_finance import fetch_fossil_finance_data  # noqa: E402
from ingest.gcpt import fetch_gcpt_data  # noqa: E402
from ingest.gogel import fetch_gogel_data  # noqa: E402
from ingest.goget import fetch_goget_data  # noqa: E402
from ingest.lobby_map import fetch_lobby_map_data  # noqa: E402
from ingest.sbti import fetch_sbti_data  # noqa: E402
from ingest.source_document import _fetch_content, _linked_report  # noqa: E402
from ingest.tpi import fetch_tpi_data  # noqa: E402
from models.claim import Claim, ClaimCategory, SourceType  # noqa: E402
from models.company import Company  # noqa: E402
from models.evidence import Evidence  # noqa: E402

Fetcher = Callable[..., Awaitable[list[Evidence]]]

_FETCHERS: tuple[tuple[str, Fetcher], ...] = (
    ("SBTi", fetch_sbti_data),
    ("E-PRTR", fetch_eprtr_data),
    ("CDP", fetch_cdp_data),
    ("EUR-Lex", fetch_eurlex_data),
    ("Banking on Climate Chaos", fetch_fossil_finance_data),
    ("Global Coal Exit List", fetch_coal_exit_data),
    ("Enforcement records", fetch_enforcement_data),
    ("LobbyMap", fetch_lobby_map_data),
    ("EU Innovation Fund", fetch_eu_innovation_fund_data),
    ("Global Oil and Gas Exit List", fetch_gogel_data),
    ("Eurostat", fetch_eurostat_data),
    ("EU Transparency Register", fetch_eu_transparency_register_data),
    ("EEA national inventory", fetch_eea_national_data),
    ("EDGAR", fetch_edgar_data),
    ("Europe Gas Tracker", fetch_egt_data),
    ("GOGET", fetch_goget_data),
    ("GCPT", fetch_gcpt_data),
    ("TPI", fetch_tpi_data),
    ("Climate Action 100+", fetch_ca100_data),
    ("Climate TRACE", fetch_climate_trace_data),
)

# raw_data keys that name the entity a source matched.
_NAME_KEYS = ("company", "name", "entity", "party", "organization", "organisation", "registrant")


async def _company(name: str) -> Company | None:
    """Load the company as the context agent does, by its name-derived id."""
    company_id = uuid.uuid5(uuid.NAMESPACE_DNS, name.lower())
    async with get_session() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT id, name, lei, isin, ticker, country, sector, sub_sector, "
                        "eu_ets_installation_ids, transparency_register_id, ir_page_url, "
                        "csrd_reporting, created_at, updated_at "
                        "FROM companies WHERE id = :company_id"
                    ),
                    {"company_id": str(company_id)},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        return None
    return Company(
        id=row["id"],
        name=row["name"],
        lei=row["lei"],
        isin=row["isin"],
        ticker=row["ticker"],
        country=row["country"],
        sector=row["sector"],
        sub_sector=row["sub_sector"],
        eu_ets_installation_ids=list(row["eu_ets_installation_ids"] or []),
        transparency_register_id=row["transparency_register_id"],
        ir_page_url=row["ir_page_url"],
        csrd_reporting=bool(row["csrd_reporting"]),
    )


def _names(record: Evidence) -> str:
    """Return the entity names a record's raw data carries, for checking the match."""
    found: list[str] = []
    for key, value in (record.raw_data or {}).items():
        if (
            isinstance(value, str)
            and any(part in key.lower() for part in _NAME_KEYS)
            and value
            and len(value) <= 90
            and value not in found
        ):
            found.append(value)
    return "; ".join(found[:4])


async def _entry_page(url: str) -> str:
    """Report the entry page's status and the report it links to."""
    try:
        content_type, body = await _fetch_content(url)
    except Exception as exc:
        return f"entry page: FAILED ({exc})"
    linked = None
    if "html" in content_type.lower():
        linked = _linked_report(body.decode("utf-8", errors="replace"), url)
    return f"entry page: OK, {len(body) // 1024} KB; linked report: {linked or 'none found'}"


async def check(name: str, url: str | None) -> None:
    """Print what every data source returns for one company."""
    print(f"\n=== {name}")
    company = await _company(name)
    if company is None:
        print("  NOT IN THE COMPANIES TABLE: the run would use a stub record")
        return
    print(
        f"  stored as {company.name!r}, country {company.country}, sector {company.sector}, "
        f"{len(company.eu_ets_installation_ids)} EU ETS installation(s)"
    )
    if url:
        print(f"  {await _entry_page(url)}")
    claim = Claim(
        trace_id=uuid.uuid4(),
        company_id=company.id,
        source_url=url or "https://www.prasineindex.com",
        source_type=SourceType.WEBSITE,
        raw_text=f"{company.name} aims to reach net zero by 2050.",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
    )
    calls: list[tuple[str, Awaitable[list[Evidence]]]] = [
        (label, fetch(claim=claim, company=company)) for label, fetch in _FETCHERS
    ]
    if company.eu_ets_installation_ids:
        calls.append(
            (
                "EU ETS",
                fetch_eu_ets_data(claim=claim, installation_ids=company.eu_ets_installation_ids),
            )
        )
    results: list[Any] = await asyncio.gather(*(c for _, c in calls), return_exceptions=True)
    for (label, _), result in zip(calls, results, strict=True):
        if isinstance(result, BaseException):
            print(f"  {label:30} ERROR {type(result).__name__}: {str(result)[:160]}")
            continue
        if not result:
            print(f"  {label:30} no record")
            continue
        first = result[0]
        names = _names(first)
        summary = " ".join(first.summary.split())[:200]
        print(f"  {label:30} {len(result)} record(s){f' [{names}]' if names else ''}")
        print(f"  {'':30} {summary}")


async def main(pairs: list[str]) -> None:
    await init_db()
    try:
        for pair in pairs:
            name, _, url = pair.partition("=")
            await check(name.strip(), url.strip() or None)
    finally:
        await teardown_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "companies", nargs="+", help='"Company name=entry URL"; the URL is optional'
    )
    asyncio.run(main(parser.parse_args().companies))

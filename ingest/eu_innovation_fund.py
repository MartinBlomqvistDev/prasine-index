"""EU Innovation Fund grant database ingest module for the Prasine Index.

Loads the European Commission Innovation Fund projects CSV from
data/eu_innovation_fund_projects.csv, downloaded via
scripts/refresh_eu_innovation_fund.py.

The EU Innovation Fund is one of the world's largest clean-tech funding programmes,
financing innovative low-carbon technologies across the EU. Grants are awarded by
the European Commission after independent expert evaluation — a grant award
constitutes validated external interest in a project, though it does not constitute
verified emissions reduction or project completion.

For greenwashing assessment, an Innovation Fund grant is:
  - Partially supporting: the EC experts evaluated the project as technically viable
    and worth funding. This mitigates pure-speculation claims.
  - Not fully exonerating: the grant was for early-stage/demonstration technology,
    not for verified delivered emissions reductions.
  - Material context: a known grant amount (e.g. EUR 54M) makes a claim more
    specific and verifiable than a purely aspirational statement.

Data source: European Commission open data portal
Refresh: python scripts/refresh_eu_innovation_fund.py
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eu_innovation_fund_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_EIF_CSV: Path = Path(
    os.environ.get(
        "EU_INNOVATION_FUND_CSV",
        str(_PROJECT_ROOT / "data" / "eu_innovation_fund_projects.csv"),
    )
)

# Column name variants across different EC open data export formats
_COL_PROJECT = ("Project name", "project_name", "Project", "Title", "Name")
_COL_COMPANY = (
    "Promoter",
    "promoter",
    "Company",
    "Beneficiary",
    "Grant recipient",
    "Legal entity",
    "Organisation",
    "Applicant",
)
_COL_COUNTRY = ("Country", "country", "Member State", "member_state", "Location")
_COL_GRANT = (
    "Grant amount (EUR)",
    "grant_amount_eur",
    "Grant (EUR)",
    "EU grant (EUR)",
    "Awarded grant",
    "Grant awarded",
    "EU contribution",
)
_COL_YEAR = ("Year", "year", "Call", "Call year", "Decision year", "Award year")
_COL_SECTOR = ("Sector", "sector", "Technology", "Technology category", "Category")
_COL_STATUS = ("Status", "status", "Project status", "Phase")
_COL_DESCRIPTION = (
    "Description",
    "description",
    "Project description",
    "Abstract",
    "Summary",
)


class _EIFProject:
    """Internal representation of one EU Innovation Fund project."""

    __slots__ = (
        "country",
        "description",
        "grant_eur",
        "project_name",
        "promoter",
        "sector",
        "status",
        "year",
    )

    def __init__(
        self,
        project_name: str,
        promoter: str,
        country: str,
        grant_eur: float | None,
        year: int | None,
        sector: str,
        status: str,
        description: str,
    ) -> None:
        self.project_name = project_name
        self.promoter = promoter
        self.country = country
        self.grant_eur = grant_eur
        self.year = year
        self.sector = sector
        self.status = status
        self.description = description


# Module-level cache
_cache_by_name: dict[str, list[_EIFProject]] | None = None
_cache_by_promoter: dict[str, list[_EIFProject]] | None = None


def refresh_cache() -> None:
    """Reset the Innovation Fund cache so the next call reloads from disk."""
    global _cache_by_name, _cache_by_promoter
    _cache_by_name = None
    _cache_by_promoter = None
    logger.info("EU Innovation Fund cache cleared.", extra={"operation": "eif_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _parse_float(value: str) -> float | None:
    cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    m = re.search(r"\d{4}", value)
    return int(m.group()) if m else None


def _normalise_name(name: str) -> str:
    name = name.lower().strip()
    for suffix in (
        " plc",
        " ag",
        " se",
        " sa",
        " s.a.",
        " spa",
        " ab",
        " as",
        " a/s",
        " nv",
        " bv",
        " gmbh",
        " inc",
        " corp",
        " ltd",
        " limited",
        " group",
        " holding",
        " holdings",
    ):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> tuple[
    dict[str, list[_EIFProject]],
    dict[str, list[_EIFProject]],
]:
    global _cache_by_name, _cache_by_promoter

    if _cache_by_promoter is not None:
        return _cache_by_name, _cache_by_promoter  # type: ignore[return-value]

    if not _EIF_CSV.exists():
        _cache_by_name = {}
        _cache_by_promoter = {}
        logger.info(
            "EU Innovation Fund data file not found — run scripts/refresh_eu_innovation_fund.py. "
            f"Expected at: {_EIF_CSV}",
            extra={"operation": "eif_cache_missing"},
        )
        return _cache_by_name, _cache_by_promoter

    by_name: dict[str, list[_EIFProject]] = {}
    by_promoter: dict[str, list[_EIFProject]] = {}

    with _EIF_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            project_name = _pick(row, _COL_PROJECT)
            promoter = _pick(row, _COL_COMPANY)
            if not project_name and not promoter:
                continue
            project = _EIFProject(
                project_name=project_name,
                promoter=promoter,
                country=_pick(row, _COL_COUNTRY),
                grant_eur=_parse_float(_pick(row, _COL_GRANT)),
                year=_parse_int(_pick(row, _COL_YEAR)),
                sector=_pick(row, _COL_SECTOR),
                status=_pick(row, _COL_STATUS),
                description=_pick(row, _COL_DESCRIPTION),
            )
            norm_project = _normalise_name(project_name)
            norm_promoter = _normalise_name(promoter)
            by_name.setdefault(norm_project, []).append(project)
            if norm_promoter:
                by_promoter.setdefault(norm_promoter, []).append(project)

    _cache_by_name = by_name
    _cache_by_promoter = by_promoter

    total = sum(len(v) for v in by_promoter.values())
    logger.info(
        f"EU Innovation Fund cache loaded: {total} projects from "
        f"{len(by_promoter)} promoters",
        extra={"operation": "eif_cache_loaded"},
    )
    return _cache_by_name, _cache_by_promoter


def _lookup(company_name: str, isin: str | None = None) -> list[_EIFProject]:
    by_name, by_promoter = _get_cache()
    norm = _normalise_name(company_name)

    results: list[_EIFProject] = []

    # Exact promoter match
    if norm in by_promoter:
        results.extend(by_promoter[norm])

    # Substring match on promoter
    if not results:
        for key, projects in by_promoter.items():
            if norm in key or key in norm:
                results.extend(projects)

    # Project name match (catches consortium/project-name-only entries)
    if not results:
        for key, projects in by_name.items():
            if norm in key or key in norm:
                results.extend(projects)

    return results


async def fetch_eu_innovation_fund_data(claim: Claim, company: object) -> list[Evidence]:
    """Return EU Innovation Fund grant evidence for a company.

    A confirmed EC Innovation Fund grant indicates that independent technical
    experts evaluated the project as viable — this is partially mitigating
    evidence for CCS or clean-tech claims. It does not confirm delivered
    emissions reductions.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A list of Evidence records for each matched project, or empty if
        no Innovation Fund grants are found for this company.
    """
    name: str = getattr(company, "name", "")
    isin: str | None = getattr(company, "isin", None)

    projects = _lookup(name, isin)

    if not projects:
        logger.info(
            f"EU Innovation Fund: no grants found for {name!r}",
            extra={"operation": "eif_not_found", "company": name},
        )
        return []

    results = []
    for project in projects:
        grant_str = (
            f"EUR {project.grant_eur:,.0f}" if project.grant_eur else "amount not disclosed"
        )
        year_str = str(project.year) if project.year else "year not recorded"
        summary = (
            f"EU Innovation Fund: {name!r} (promoter: {project.promoter!r}) received "
            f"an Innovation Fund grant of {grant_str} in {year_str} for project "
            f"{project.project_name!r} (sector: {project.sector or 'unspecified'}, "
            f"status: {project.status or 'unspecified'}). "
            f"An Innovation Fund award indicates independent EC technical evaluation "
            f"confirmed the project's low-carbon technology viability. "
            f"This partially substantiates technology-specific claims but does not "
            f"confirm delivered emissions reductions or certified carbon removals."
        )
        if project.description:
            summary += f" Project description: {project.description[:200]}."

        logger.info(
            f"EU Innovation Fund: {name!r} matched project {project.project_name!r} "
            f"grant={grant_str} year={year_str}",
            extra={"operation": "eif_found", "company": name},
        )

        results.append(
            Evidence(
                claim_id=claim.id,
                trace_id=claim.trace_id,
                source=EvidenceSource.EU_INNOVATION_FUND,
                evidence_type=EvidenceType.TARGET_RECORD,
                source_url="https://climate.ec.europa.eu/eu-action/eu-funding-climate-action/innovation-fund/projects-funded_en",
                raw_data={
                    "project_name": project.project_name,
                    "promoter": project.promoter,
                    "country": project.country,
                    "grant_eur": project.grant_eur,
                    "year": project.year,
                    "sector": project.sector,
                    "status": project.status,
                    "description": project.description[:500] if project.description else "",
                },
                summary=summary,
                data_year=project.year,
                # A grant is partially supporting — validates technology viability
                # but doesn't confirm actual emissions reductions
                supports_claim=None,
                confidence=0.80,
            )
        )

    return results

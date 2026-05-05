"""CDP (Carbon Disclosure Project) open data ingest module for the Prasine Index.

Loads the CDP annual bulk dataset from a local CSV file downloaded via
scripts/refresh_cdp.py. Returns empty evidence if the file is absent.

CDP data is self-reported and weighted as secondary evidence. It is the primary
source for:
  - Companies without EU ETS installations (banks, retail, services, shipping)
  - Scope 3 and value-chain emissions claims
  - Climate governance and board oversight claims
  - Emissions reduction target disclosures

A discrepancy between CDP self-reported data and EU ETS verified data is itself
a greenwashing signal — the company told CDP one thing and the regulator records
another.

NOTE: Web scraping cdp.net is not viable. The site is a fully client-side Next.js
app with no __NEXT_DATA__, no accessible JSON API endpoints, and no plain-HTML
fallback. A headless browser (Playwright) would work but is not worth the
dependency for a single letter grade. CDP bulk CSV requires free registration at
data.cdp.net — one-time download, no paywall.

Data source: data.cdp.net (annual open data download, free registration required)
Refresh: python scripts/refresh_cdp.py
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.company import Company
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_cdp_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

# Primary CDP bulk CSV — downloaded by scripts/refresh_cdp.py.
_CDP_CSV: Path = Path(
    os.environ.get(
        "CDP_CSV",
        str(_PROJECT_ROOT / "data" / "cdp_companies.csv"),
    )
)

# CDP score meanings for the Judge Agent.
_SCORE_DESCRIPTIONS: dict[str, str] = {
    "A": "Leadership — company discloses comprehensively and takes best-practice action",
    "A-": "Leadership — near-best-practice disclosure and action",
    "B": "Management — taking coordinated action on climate issues",
    "B-": "Management — coordinated action with some gaps",
    "C": "Awareness — some climate disclosure but limited action",
    "C-": "Awareness — minimal disclosure",
    "D": "Disclosure — responding to CDP but not disclosing meaningfully",
    "D-": "Disclosure — minimum response only",
    "F": "Non-disclosure — failed to respond or responded insufficiently",
    "N/A": "Not applicable or data not available",
}

# CDP column names vary across annual releases and dataset types.
# Column names confirmed from the actual CDP open data portal CSV exports.
#
# The dataset to download is:
#   data.cdp.net → filter Category: "Companies" → search "climate change scores"
#   → download the most recent year's "Climate Change Scores" CSV.
#
# Known column variants by year:
#   2023/2024: "Account Name", "Country/Area", "Primary Sector", "Score"
#   2021/2022: "Organization", "Country", "Sector", "Climate Change Score"
#   2019/2020: "Company Name", "Country", "Industry", "2020 Score"
#   Older Global 500 datasets: "Company", "Country", "Sector", "Score"
_COL_ORG = (
    "Account Name",  # 2023/2024 format (current)
    "Organization",  # 2021/2022 format
    "Company Name",  # 2019/2020 format
    "Company",  # older Global 500 format
    "company_name",
)
_COL_ISIN = ("ISIN", "isin", "Primary ISIN", "ISIN Code")
_COL_LEI = ("LEI", "lei", "Primary LEI", "LEI Code")
_COL_SCORE = (
    "Score",  # 2023/2024 — current standard column name
    "Climate Change Score",  # 2021/2022 format
    "2024 Score",
    "2023 Score",
    "2022 Score",
    "2021 Score",
    "2020 Score",
    "CDP Score",
    "score",
)
_COL_YEAR = ("Reporting Year", "Year", "Survey Year", "year", "Disclosure Year")
_COL_SECTOR = (
    "Primary Sector",  # 2023/2024 — current
    "Sector",  # older formats
    "Industry Sector",
    "sector",
    "Industry",
)
_COL_COUNTRY = (
    "Country/Area",  # 2023/2024 — current
    "Country",  # older formats
    "HQ Country",
    "country",
)


class _CDPRecord:
    """Internal representation of one CDP company record."""

    __slots__ = ("country", "isin", "lei", "name", "score", "sector", "year")

    def __init__(
        self,
        name: str,
        isin: str | None,
        lei: str | None,
        score: str,
        year: int | None,
        sector: str,
        country: str,
    ) -> None:
        self.name = name
        self.isin = isin
        self.lei = lei
        self.score = score
        self.year = year
        self.sector = sector
        self.country = country


# Module-level caches.
_cache_by_isin: dict[str, _CDPRecord] | None = None
_cache_by_lei: dict[str, _CDPRecord] | None = None
_cache_by_name: dict[str, _CDPRecord] | None = None


def refresh_cache() -> None:
    """Reset the CDP cache so the next call reloads from disk."""
    global _cache_by_isin, _cache_by_lei, _cache_by_name
    _cache_by_isin = None
    _cache_by_lei = None
    _cache_by_name = None
    logger.info("CDP cache cleared.", extra={"operation": "cdp_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _normalise_name(name: str) -> str:
    name = name.lower().strip()
    for suffix in (
        " plc",
        " ag",
        " se",
        " sa",
        " s.a.",
        " spa",
        " s.p.a.",
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
    dict[str, _CDPRecord],
    dict[str, _CDPRecord],
    dict[str, _CDPRecord],
]:
    """Return module-level caches, loading from disk on first call."""
    global _cache_by_isin, _cache_by_lei, _cache_by_name

    if _cache_by_isin is not None:
        return _cache_by_isin, _cache_by_lei, _cache_by_name  # type: ignore[return-value]

    if not _CDP_CSV.exists():
        _cache_by_isin, _cache_by_lei, _cache_by_name = {}, {}, {}
        logger.info(
            "CDP bulk CSV not found — run scripts/refresh_cdp.py to download. "
            f"Expected at: {_CDP_CSV}",
            extra={"operation": "cdp_cache_missing"},
        )
        return _cache_by_isin, _cache_by_lei, _cache_by_name

    by_isin: dict[str, _CDPRecord] = {}
    by_lei: dict[str, _CDPRecord] = {}
    by_name: dict[str, _CDPRecord] = {}

    with _CDP_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = _pick(row, _COL_ORG)
            if not name:
                continue

            year_raw = _pick(row, _COL_YEAR)
            try:
                year = int(str(year_raw)[:4]) if year_raw else None
            except ValueError:
                year = None

            record = _CDPRecord(
                name=name,
                isin=_pick(row, _COL_ISIN) or None,
                lei=_pick(row, _COL_LEI) or None,
                score=_pick(row, _COL_SCORE) or "N/A",
                year=year,
                sector=_pick(row, _COL_SECTOR),
                country=_pick(row, _COL_COUNTRY),
            )

            # Keep most recent year per identifier.
            normalised = _normalise_name(name)
            existing = by_name.get(normalised)
            if existing is None or (record.year or 0) >= (existing.year or 0):
                if record.isin:
                    by_isin[record.isin.upper()] = record
                if record.lei:
                    by_lei[record.lei.upper()] = record
                by_name[normalised] = record

    _cache_by_isin, _cache_by_lei, _cache_by_name = by_isin, by_lei, by_name

    logger.info(
        f"CDP cache loaded: {len(by_isin)} by ISIN, {len(by_lei)} by LEI, {len(by_name)} by name",
        extra={"operation": "cdp_cache_loaded"},
    )
    return _cache_by_isin, _cache_by_lei, _cache_by_name


def _lookup(company: Company) -> _CDPRecord | None:
    """Find a CDP record for the company. Tries ISIN → LEI → normalised name."""
    by_isin, by_lei, by_name = _get_cache()

    if company.isin and company.isin.upper() in by_isin:
        return by_isin[company.isin.upper()]
    if company.lei and company.lei.upper() in by_lei:
        return by_lei[company.lei.upper()]
    return by_name.get(_normalise_name(company.name))


async def fetch_cdp_data(claim: Claim, company: Company) -> list[Evidence]:
    """Fetch self-reported climate data from the local CDP bulk dataset.

    Looks up the company by ISIN, LEI, or normalised name against the
    locally cached CDP annual bulk CSV. Returns an Evidence record with
    CDP score, year, and a plain-language assessment of what the score
    means in relation to the claim.

    CDP data is self-reported and confidence is capped at 0.70. Discrepancies
    between CDP disclosures and EU ETS verified data are noted by the Judge.

    Args:
        claim: The claim under assessment.
        company: The company that made the claim.

    Returns:
        A single-element list with the CDP Evidence record, or empty list
        if the company is not in the CDP dataset.
    """
    record = _lookup(company)

    if record is None:
        logger.info(
            f"CDP: no record found for {company.name!r} "
            f"(ISIN={company.isin!r}, LEI={company.lei!r})",
            extra={"operation": "cdp_not_found", "company_id": str(company.id)},
        )
        return []

    supports, confidence = _assess_record(record, claim)
    summary = _build_summary(company.name, record)

    logger.info(
        f"CDP: {company.name!r} found — score={record.score!r}, year={record.year}",
        extra={"operation": "cdp_found", "company_id": str(company.id)},
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.CDP,
            evidence_type=EvidenceType.SELF_REPORTED_EMISSIONS,
            source_url="https://data.cdp.net",
            raw_data={
                "company": record.name,
                "isin": record.isin,
                "lei": record.lei,
                "score": record.score,
                "year": record.year,
                "sector": record.sector,
                "country": record.country,
            },
            summary=summary,
            data_year=record.year,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_record(record: _CDPRecord, claim: Claim) -> tuple[bool | None, float]:
    """Assess whether the CDP score supports or contradicts the claim.

    Args:
        record: The CDP record for the company.
        claim: The claim under assessment.

    Returns:
        Tuple of (supports_claim, confidence).
    """
    score = record.score.upper().strip()
    # CDP data is self-reported; cap confidence at 0.70.
    if score in ("A", "A-"):
        return True, 0.65
    if score in ("D", "D-", "F"):
        return False, 0.65
    if score in ("N/A", "", "NOT APPLICABLE"):
        return None, 0.4
    # B, C range — neutral signal
    return None, 0.55


def _build_summary(company_name: str, record: _CDPRecord) -> str:
    """Build a human-readable summary for the Judge Agent.

    Args:
        company_name: Display name of the company.
        record: The CDP record.

    Returns:
        A plain-text summary string.
    """
    score = record.score or "N/A"
    year_str = str(record.year) if record.year else "most recent year"
    description = _SCORE_DESCRIPTIONS.get(score, "Score description unavailable.")

    return (
        f"CDP self-reported climate disclosure for {company_name} ({year_str}): "
        f"CDP score {score}. {description}. "
        "Note: CDP data is self-reported by the company and weighted as secondary "
        "evidence. Significant discrepancies with EU ETS verified data indicate "
        "inconsistent reporting."
    )

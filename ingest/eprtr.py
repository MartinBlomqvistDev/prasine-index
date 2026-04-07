"""E-PRTR (European Pollutant Release and Transfer Register) ingest module.

Loads the EEA E-PRTR bulk CSV from data/eprtr_releases.csv, downloaded via
scripts/refresh_eprtr.py. Provides evidence of non-CO2 GHG and pollutant
releases per company, complementing EU ETS verified CO2 data.

E-PRTR covers all industrial facilities reporting under E-PRTR Regulation
(EC) No 166/2006 and the successor Industrial Emissions Directive. It captures
pollutants that EU ETS does not — methane (CH4), nitrous oxide (N2O), HFCs,
and non-GHG pollutants. A company claiming environmental leadership while
reporting high or rising non-CO2 GHG releases to E-PRTR is a greenwashing signal.

Data source: European Environment Agency (EEA)
Refresh: python scripts/refresh_eprtr.py
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eprtr_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_EPRTR_CSV: Path = Path(
    os.environ.get(
        "EPRTR_CSV",
        str(_PROJECT_ROOT / "data" / "eprtr_releases.csv"),
    )
)

# ---------------------------------------------------------------------------
# GHG pollutants tracked — all non-CO2 GHGs reportable under E-PRTR
# ---------------------------------------------------------------------------

# E-PRTR pollutant name variants across CSV vintages.
_GHG_POLLUTANTS = frozenset({
    "methane (ch4)",
    "ch4",
    "nitrous oxide (n2o)",
    "n2o",
    "hydrofluorocarbons (hfcs)",
    "hfcs",
    "perfluorocarbons (pfcs)",
    "pfcs",
    "sulphur hexafluoride (sf6)",
    "sf6",
    "nitrogen trifluoride (nf3)",
    "nf3",
    # CO2 equivalents sometimes reported separately
    "greenhouse gases",
    "ghg",
    "carbon dioxide equivalent",
    "co2 equivalent",
})

# Column name variants across EEA E-PRTR CSV vintages
_COL_FACILITY = ("facilityName", "FacilityName", "facility_name", "Facility Name", "FacilityReport_FacilityName")
_COL_PARENT = ("parentCompanyName", "ParentCompanyName", "parent_company", "Parent Company", "FacilityReport_ParentCompanyName")
_COL_YEAR = ("reportingYear", "ReportingYear", "year", "Year", "FacilityReport_ReportingYear")
_COL_POLLUTANT = ("pollutantName", "PollutantName", "pollutant_name", "Pollutant", "PollutantRelease_PollutantName")
_COL_QUANTITY = ("totalPollutantQuantityKg", "TotalQuantity", "quantity_kg", "QuantityKg", "PollutantRelease_TotalPollutantQuantityKg", "PollutantRelease_TotalQuantity")
_COL_MEDIUM = ("mediumCode", "MediumCode", "medium", "Medium", "PollutantRelease_MediumCode")
_COL_COUNTRY = ("countryCode", "CountryCode", "country_code", "Country", "FacilityReport_CountryCode")


class _EprtrRecord:
    """One pollutant release record from the E-PRTR dataset."""

    __slots__ = ("facility_name", "parent_company", "country", "year", "pollutant", "quantity_kg", "medium")

    def __init__(
        self,
        facility_name: str,
        parent_company: str,
        country: str,
        year: int,
        pollutant: str,
        quantity_kg: float,
        medium: str,
    ) -> None:
        self.facility_name = facility_name
        self.parent_company = parent_company
        self.country = country
        self.year = year
        self.pollutant = pollutant
        self.quantity_kg = quantity_kg
        self.medium = medium

    @property
    def is_ghg(self) -> bool:
        return self.pollutant.lower().strip() in _GHG_POLLUTANTS

    @property
    def quantity_tonnes(self) -> float:
        return self.quantity_kg / 1000.0


# Module-level cache:
# {normalised_parent: {year: [_EprtrRecord, ...]}}
# {normalised_facility: {year: [_EprtrRecord, ...]}}
_cache_by_parent: dict[str, dict[int, list[_EprtrRecord]]] | None = None
_cache_by_facility: dict[str, dict[int, list[_EprtrRecord]]] | None = None


def refresh_cache() -> None:
    """Reset the E-PRTR cache so the next call reloads from disk.

    Call this after running scripts/refresh_eprtr.py.
    """
    global _cache_by_parent, _cache_by_facility
    _cache_by_parent = None
    _cache_by_facility = None
    logger.info("E-PRTR cache cleared.", extra={"operation": "eprtr_cache_reset"})


def _pick(row: dict[str, str], candidates: tuple[str, ...]) -> str:
    """Return the value of the first matching column name, or empty string."""
    for key in candidates:
        if key in row:
            return row[key].strip()
    return ""


def _normalise_name(name: str) -> str:
    """Lowercase and strip legal suffixes for fuzzy matching."""
    name = name.lower().strip()
    for suffix in (" plc", " ag", " se", " sa", " s.a.", " spa", " s.p.a.", " nv",
                   " bv", " gmbh", " inc", " corp", " ltd", " limited", " group",
                   " holding", " holdings"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _get_cache() -> tuple[
    dict[str, dict[int, list[_EprtrRecord]]],
    dict[str, dict[int, list[_EprtrRecord]]],
]:
    """Return module-level caches, loading from disk on first call."""
    global _cache_by_parent, _cache_by_facility

    if _cache_by_parent is not None:
        return _cache_by_parent, _cache_by_facility  # type: ignore[return-value]

    if not _EPRTR_CSV.exists():
        _cache_by_parent = {}
        _cache_by_facility = {}
        logger.info(
            "E-PRTR data file not found — run scripts/refresh_eprtr.py to download. "
            f"Expected at: {_EPRTR_CSV}",
            extra={"operation": "eprtr_cache_missing"},
        )
        return _cache_by_parent, _cache_by_facility

    by_parent: dict[str, dict[int, list[_EprtrRecord]]] = defaultdict(lambda: defaultdict(list))
    by_facility: dict[str, dict[int, list[_EprtrRecord]]] = defaultdict(lambda: defaultdict(list))
    row_count = 0

    with _EPRTR_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            facility = _pick(row, _COL_FACILITY)
            parent = _pick(row, _COL_PARENT) or facility
            year_str = _pick(row, _COL_YEAR)
            pollutant = _pick(row, _COL_POLLUTANT)
            quantity_str = _pick(row, _COL_QUANTITY)
            medium = _pick(row, _COL_MEDIUM)
            country = _pick(row, _COL_COUNTRY)

            if not (facility and year_str and pollutant and quantity_str):
                continue

            try:
                year = int(year_str)
                quantity_kg = float(quantity_str.replace(",", "").replace(" ", ""))
            except ValueError:
                continue

            record = _EprtrRecord(
                facility_name=facility,
                parent_company=parent,
                country=country,
                year=year,
                pollutant=pollutant,
                quantity_kg=quantity_kg,
                medium=medium,
            )
            norm_parent = _normalise_name(parent)
            norm_facility = _normalise_name(facility)
            by_parent[norm_parent][year].append(record)
            by_facility[norm_facility][year].append(record)
            row_count += 1

    # Convert defaultdicts to regular dicts to avoid unexpected expansion
    _cache_by_parent = {k: dict(v) for k, v in by_parent.items()}
    _cache_by_facility = {k: dict(v) for k, v in by_facility.items()}

    logger.info(
        f"E-PRTR cache loaded: {row_count} releases, {len(_cache_by_parent)} companies",
        extra={"operation": "eprtr_cache_loaded", "row_count": row_count},
    )
    return _cache_by_parent, _cache_by_facility


def _lookup(name: str) -> dict[int, list[_EprtrRecord]]:
    """Look up all E-PRTR records for a company by normalised name.

    Checks parent company name first, then facility name.

    Args:
        name: The company name to look up.

    Returns:
        Dict mapping year → list of release records for that year.
    """
    by_parent, by_facility = _get_cache()
    norm = _normalise_name(name)

    if norm in by_parent:
        return by_parent[norm]

    # Partial match on parent: company name appears as substring
    for key, records in by_parent.items():
        if norm in key or key in norm:
            return records

    if norm in by_facility:
        return by_facility[norm]

    return {}


def _ghg_tonnes_by_year(records_by_year: dict[int, list[_EprtrRecord]]) -> dict[int, float]:
    """Sum all GHG releases per year in tonnes.

    Args:
        records_by_year: Year → list of release records.

    Returns:
        Year → total GHG in tonnes (summed across all facilities and pollutants).
    """
    result: dict[int, float] = {}
    for year, records in sorted(records_by_year.items()):
        ghg_sum = sum(r.quantity_tonnes for r in records if r.is_ghg and r.medium.upper() == "AIR")
        if ghg_sum > 0:
            result[year] = ghg_sum
    return result


async def fetch_eprtr_data(claim: Claim, company: object) -> list[Evidence]:
    """Return E-PRTR non-CO2 GHG release evidence for a company.

    Looks up the company's industrial facility releases from the E-PRTR dataset.
    GHG releases (CH4, N2O, HFCs, etc.) are summed per year and assessed for
    trend direction. Rising non-CO2 GHG releases while claiming environmental
    leadership is a greenwashing signal.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with an Evidence record, or empty list if no
        E-PRTR records are found for the company.
    """
    name: str = getattr(company, "name", "")
    isin: str | None = getattr(company, "isin", None)

    records_by_year = _lookup(name)

    if not records_by_year:
        logger.info(
            f"E-PRTR: no records found for {name!r}",
            extra={"operation": "eprtr_not_found", "company": name},
        )
        return []

    ghg_by_year = _ghg_tonnes_by_year(records_by_year)

    if not ghg_by_year:
        # Records found but no GHG releases to AIR — return empty so as not to confuse the Judge.
        return []

    years = sorted(ghg_by_year.keys())
    latest_year = years[-1]
    latest_tonnes = ghg_by_year[latest_year]

    # Build trend assessment
    supports, confidence, trend_text = _assess_trend(ghg_by_year)

    # Build year-by-year summary for the Judge (last 5 years)
    year_lines = [
        f"{yr}: {ghg_by_year[yr]:,.1f} t GHG"
        for yr in years[-5:]
    ]
    summary = (
        f"E-PRTR non-CO2 GHG releases to air for {name}: {'; '.join(year_lines)}. "
        f"Most recent year ({latest_year}): {latest_tonnes:,.1f} tonnes. "
        f"{trend_text}"
    )

    logger.info(
        f"E-PRTR: {name!r} — {latest_year} GHG={latest_tonnes:,.1f} t, trend={trend_text!r}",
        extra={
            "operation": "eprtr_found",
            "company": name,
            "latest_year": latest_year,
            "latest_ghg_t": latest_tonnes,
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.EPRTR,
            evidence_type=EvidenceType.POLLUTION_RECORD,
            source_url="https://industry.eea.europa.eu/",
            raw_data={
                "company": name,
                "ghg_by_year": ghg_by_year,
                "years_available": years,
                "latest_year": latest_year,
                "latest_ghg_tonnes": latest_tonnes,
            },
            summary=summary,
            data_year=latest_year,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_trend(ghg_by_year: dict[int, float]) -> tuple[bool | None, float, str]:
    """Assess whether the GHG release trend supports or contradicts a green claim.

    Args:
        ghg_by_year: Year → total GHG tonnes for the company.

    Returns:
        Tuple of (supports_claim, confidence, human-readable trend description).
    """
    if len(ghg_by_year) < 2:
        year = list(ghg_by_year.keys())[0]
        return None, 0.4, f"Only one year of data ({year}) — trend cannot be assessed."

    years = sorted(ghg_by_year.keys())
    first_year, first_val = years[0], ghg_by_year[years[0]]
    last_year, last_val = years[-1], ghg_by_year[years[-1]]

    if first_val == 0:
        return None, 0.4, "Baseline year has zero GHG releases — trend unreliable."

    pct_change = (last_val - first_val) / first_val * 100

    if pct_change <= -30:
        return (
            True, 0.75,
            f"GHG releases fell {abs(pct_change):.0f}% from {first_year} to {last_year} "
            f"({first_val:,.1f} → {last_val:,.1f} t). Supports emissions reduction claims."
        )
    if pct_change >= 20:
        return (
            False, 0.75,
            f"GHG releases rose {pct_change:.0f}% from {first_year} to {last_year} "
            f"({first_val:,.1f} → {last_val:,.1f} t). Contradicts emissions reduction claims."
        )

    # Flat or modest change — inconclusive
    direction = "fell" if pct_change < 0 else "rose"
    return (
        None, 0.55,
        f"GHG releases {direction} {abs(pct_change):.0f}% from {first_year} to {last_year} "
        f"({first_val:,.1f} → {last_val:,.1f} t). Inconclusive."
    )

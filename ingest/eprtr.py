"""E-PRTR (European Pollutant Release and Transfer Register) ingest module.

Loads the EEA E-PRTR bulk CSV from data/eprtr_releases.csv, downloaded via
scripts/refresh_eprtr.py. Provides evidence of non-CO2 GHG and pollutant
releases per company, complementing EU ETS verified CO2 data.

E-PRTR covers all industrial facilities reporting under E-PRTR Regulation
(EC) No 166/2006 and the successor Industrial Emissions Directive. It captures
pollutants that EU ETS does not: methane (CH4), nitrous oxide (N2O), HFCs,
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
from ingest.name_matching import contains_name
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
# Regulated air emissions tracked from E-PRTR
# ---------------------------------------------------------------------------

# Pollutant name variants as they appear in the EEA E-PRTR CSV (lowercased).
# Covers GHGs (CH4, N2O, F-gases) plus CO2 and major air pollutants that are
# directly relevant to corporate green claims. CO2 is included here because
# E-PRTR captures industrial CO2 from facilities not covered by EU ETS (e.g.
# wood manufacturing, retail logistics, food processing), which is the only
# source of verified CO2 data for non-ETS companies.
_TRACKED_POLLUTANTS = frozenset(
    {
        # GHGs
        "methane (ch4)",
        "ch4",
        "nitrous oxide (n2o)",
        "n2o",
        # F-gases: CSV uses "hydro-fluorocarbons" (with hyphen)
        "hydro-fluorocarbons (hfcs)",
        "hydrofluorocarbons (hfcs)",
        "hfcs",
        "hydrochlorofluorocarbons (hcfcs)",
        "hcfcs",
        "chlorofluorocarbons (cfcs)",
        "cfcs",
        "halons",
        "perfluorocarbons (pfcs)",
        "pfcs",
        "sulphur hexafluoride (sf6)",
        "sf6",
        "nitrogen trifluoride (nf3)",
        "nf3",
        # CO2: relevant for non-EU-ETS industrial facilities
        "carbon dioxide (co2)",
        "carbon dioxide (co2) excluding biomass",
        "co2",
        # CO2 equivalents
        "greenhouse gases",
        "ghg",
        "carbon dioxide equivalent",
        "co2 equivalent",
        # Major air pollutants: directly relevant to "environmental leadership" claims
        "nitrogen oxides (nox)",
        "nox",
        "non-methane volatile organic compounds (nmvoc)",
        "nmvoc",
    }
)

# Column name variants across EEA E-PRTR CSV vintages
_COL_FACILITY = (
    "facilityName",
    "FacilityName",
    "facility_name",
    "Facility Name",
    "FacilityReport_FacilityName",
)
_COL_PARENT = (
    "parentCompanyName",
    "ParentCompanyName",
    "parent_company",
    "Parent Company",
    "FacilityReport_ParentCompanyName",
)
_COL_YEAR = ("reportingYear", "ReportingYear", "year", "Year", "FacilityReport_ReportingYear")
_COL_POLLUTANT = (
    "pollutantName",
    "PollutantName",
    "pollutant_name",
    "Pollutant",
    "PollutantRelease_PollutantName",
)
_COL_QUANTITY = (
    "totalPollutantQuantityKg",
    "TotalQuantity",
    "quantity_kg",
    "QuantityKg",
    "PollutantRelease_TotalPollutantQuantityKg",
    "PollutantRelease_TotalQuantity",
    "Releases",
)
_COL_MEDIUM = (
    "mediumCode",
    "MediumCode",
    "medium",
    "Medium",
    "PollutantRelease_MediumCode",
    "TargetRelease",
)
_COL_COUNTRY = (
    "countryCode",
    "CountryCode",
    "country_code",
    "Country",
    "FacilityReport_CountryCode",
)


class _EprtrRecord:
    """One pollutant release record from the E-PRTR dataset."""

    __slots__ = (
        "country",
        "facility_name",
        "medium",
        "parent_company",
        "pollutant",
        "quantity_kg",
        "year",
    )

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
        return self.pollutant.lower().strip() in _TRACKED_POLLUTANTS

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
        " a/s",
        " as",
        " ab",
    ):
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
            "E-PRTR data file not found: run scripts/refresh_eprtr.py to download. "
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

    Aggregates records across all matching parent company names and facility
    names: a large company like IKEA may have multiple subsidiaries (e.g.
    IKEA Industry Poland, IKEA Industry Lietuva) each stored under a different
    key. Returning only the first match would silently drop the others.

    Args:
        name: The company name to look up.

    Returns:
        Dict mapping year → list of release records (all matching facilities
        combined). Empty dict if no match found.
    """
    by_parent, by_facility = _get_cache()
    norm = _normalise_name(name)

    merged: dict[int, list[_EprtrRecord]] = defaultdict(list)

    if norm in by_parent:
        for year, records in by_parent[norm].items():
            merged[year].extend(records)

    # Partial match: collect ALL keys where the company name appears as whole words
    for key, records_by_year in by_parent.items():
        if key == norm:
            continue  # already handled above
        # A short name such as "bp" matches only where a key starts with it, so that
        # "BP Europa SE" is found and "Aker BP" is not.
        if (len(norm) >= 4 and contains_name(key, norm)) or (
            2 <= len(norm) < 4 and key.startswith(f"{norm} ")
        ):
            for year, records in records_by_year.items():
                merged[year].extend(records)

    if merged:
        return dict(merged)

    # Fallback: facility name match
    if norm in by_facility:
        return by_facility[norm]

    return {}


# Carbon dioxide as E-PRTR names it. Some facilities also report CO2 "excluding
# biomass", but the two figures are not reported consistently (some facilities
# report more CO2 excluding biomass than in total), so only the total is summed
# and the other figure is noted.
_CO2_NAMES = frozenset({"carbon dioxide (co2)", "co2"})
_CO2_FOSSIL = "carbon dioxide (co2) excluding biomass"


def _air(record: _EprtrRecord) -> bool:
    return record.is_ghg and record.medium.upper() == "AIR"


def _co2_by_year(records_by_year: dict[int, list[_EprtrRecord]]) -> dict[int, float]:
    """Sum the total CO2 released to air by all matched facilities, per year, in tonnes."""
    result: dict[int, float] = {}
    for year, records in sorted(records_by_year.items()):
        total = sum(
            r.quantity_tonnes
            for r in records
            if _air(r) and r.pollutant.lower().strip() in _CO2_NAMES
        )
        if total > 0:
            result[year] = total
    return result


def _co2_facilities(records_by_year: dict[int, list[_EprtrRecord]]) -> dict[int, int]:
    """Count the matched facilities that report total CO2 to air, per year."""
    return {
        year: len(
            {
                r.facility_name
                for r in records
                if _air(r) and r.pollutant.lower().strip() in _CO2_NAMES
            }
        )
        for year, records in records_by_year.items()
    }


def _other_pollutants(records: list[_EprtrRecord]) -> dict[str, float]:
    """Sum each tracked pollutant other than CO2 released to air, in tonnes."""
    totals: dict[str, float] = defaultdict(float)
    for r in records:
        name = r.pollutant.lower().strip()
        if _air(r) and name not in _CO2_NAMES and "excluding biomass" not in name:
            totals[r.pollutant.strip()] += r.quantity_tonnes
    return {name: value for name, value in totals.items() if value > 0}


def _ghg_tonnes_by_year(records_by_year: dict[int, list[_EprtrRecord]]) -> dict[int, float]:
    """Sum all tracked regulated emissions per year in tonnes.

    Covers GHGs (CH4, N2O, F-gases), CO2 from non-ETS industrial facilities,
    and major air pollutants (NOX, NMVOC), all reported to air medium only.

    Args:
        records_by_year: Year → list of release records.

    Returns:
        Year → total regulated emissions in tonnes.
    """
    result: dict[int, float] = {}
    for year, records in sorted(records_by_year.items()):
        total = sum(r.quantity_tonnes for r in records if r.is_ghg and r.medium.upper() == "AIR")
        if total > 0:
            result[year] = total
    return result


async def fetch_eprtr_data(claim: Claim, company: object) -> list[Evidence]:
    """Return E-PRTR regulated emissions evidence for a company.

    Looks up the company's industrial facility releases from the E-PRTR dataset,
    aggregating across all subsidiary facilities. Tracked pollutants include GHGs
    (CH4, N2O, F-gases), CO2 from non-EU-ETS facilities, NOX, and NMVOC, all
    reported to air. Rising industrial emissions while claiming environmental
    leadership is a greenwashing signal.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with an Evidence record, or empty list if no
        E-PRTR records are found for the company.
    """
    name: str = getattr(company, "name", "")

    records_by_year = _lookup(name)

    if not records_by_year:
        logger.info(
            f"E-PRTR: no records found for {name!r}",
            extra={"operation": "eprtr_not_found", "company": name},
        )
        return []

    co2_by_year = _co2_by_year(records_by_year)
    tracked_years = sorted(
        year for year, records in records_by_year.items() if any(_air(r) for r in records)
    )
    if not tracked_years:
        # Records found but no tracked releases to air: nothing to report.
        return []

    latest_year = tracked_years[-1]
    latest_records = [r for r in records_by_year[latest_year] if _air(r)]
    facilities = sorted({r.facility_name for r in latest_records})
    named = "; ".join(facilities[:4]) + (
        f"; and {len(facilities) - 4} more" if len(facilities) > 4 else ""
    )
    others = _other_pollutants(latest_records)
    other_text = "; ".join(
        f"{pollutant} {tonnes:,.1f} t" for pollutant, tonnes in sorted(others.items())
    )

    parts = [
        f"E-PRTR releases to air from {len(facilities)} "
        f"{'facility whose name matches' if len(facilities) == 1 else 'facilities whose names match'} {name} "
        f"in {latest_year} ({named}). Each pollutant is reported separately."
    ]
    if co2_by_year:
        years = sorted(co2_by_year)
        counts = _co2_facilities(records_by_year)

        def covered(yr: int) -> str:
            n = counts.get(yr, 0)
            return f"{n} {'facility' if n == 1 else 'facilities'}"

        series = "; ".join(
            f"{yr}: {co2_by_year[yr]:,.1f} t from {covered(yr)}" for yr in years[-5:]
        )
        supports, confidence, trend_text = _assess_trend(co2_by_year)
        parts.append(f"Carbon dioxide (CO2), total as reported: {series}. {trend_text}")
        if counts.get(years[0]) != counts.get(years[-1]):
            parts.append(
                f"The first year, {years[0]}, covers {covered(years[0])} and the last, "
                f"{years[-1]}, {covered(years[-1])}, so the change between them is not like "
                "for like."
            )
    else:
        supports, confidence, trend_text = None, 0.4, "no CO2 reported"
        parts.append("No CO2 release is reported for these facilities.")
    if other_text:
        parts.append(f"Other pollutants in {latest_year}: {other_text}.")
    if any(r.pollutant.lower().strip() == _CO2_FOSSIL for r in latest_records):
        parts.append(
            "Some of these facilities also report CO2 excluding biomass, a figure not "
            "combined with the totals above."
        )
    elif co2_by_year:
        parts.append(
            "E-PRTR's CO2 total includes CO2 from burning biomass, and these facilities "
            "report no figure excluding biomass."
        )
    summary = " ".join(parts)
    ghg_by_year = co2_by_year
    latest_tonnes = co2_by_year.get(latest_year, 0.0)

    logger.info(
        f"E-PRTR: {name!r}, {latest_year} emissions={latest_tonnes:,.1f} t, trend={trend_text!r}",
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
                "facilities": facilities,
                "co2_by_year": ghg_by_year,
                "other_pollutants_latest_year": others,
                "years_available": tracked_years,
                "latest_year": latest_year,
                "latest_co2_tonnes": latest_tonnes,
            },
            summary=summary,
            data_year=latest_year,
            supports_claim=supports,
            confidence=confidence,
        )
    ]


def _assess_trend(ghg_by_year: dict[int, float]) -> tuple[bool | None, float, str]:
    """Assess whether the emissions trend supports or contradicts a green claim.

    Compares the first and the last year of the series. A last year more than ten
    times the year before is read as a first-disclosure event (a facility or
    pollutant entering the reporting scope), and the trend is then taken without
    it. E-PRTR reporting scope changes, for example a facility crossing the
    reporting threshold, produce step-changes that are not real emissions trends,
    and the summary states how many facilities each year covers.

    Args:
        ghg_by_year: Year → total regulated emissions in tonnes.

    Returns:
        Tuple of (supports_claim, confidence, human-readable trend description).
    """
    if len(ghg_by_year) < 2:
        year = next(iter(ghg_by_year.keys()))
        return None, 0.4, f"Only one year of data ({year}), trend cannot be assessed."

    years = sorted(ghg_by_year.keys())
    vals = [ghg_by_year[y] for y in years]

    # Detect a step-change in the final year: last value is >10x the
    # second-to-last value and there are ≥3 years of prior data. This
    # pattern indicates a first-disclosure event (new facility/pollutant
    # entering the dataset) rather than a genuine emissions increase.
    if len(years) >= 3:
        penultimate = ghg_by_year[years[-2]]
        last_val = ghg_by_year[years[-1]]
        if penultimate > 0 and last_val / penultimate > 10:
            # Use the trend excluding the final spike year for assessment.
            prior_years = years[:-1]
            prior_vals = [ghg_by_year[y] for y in prior_years]
            prior_first, prior_last = prior_vals[0], prior_vals[-1]
            if prior_first > 0:
                prior_pct = (prior_last - prior_first) / prior_first * 100
            else:
                prior_pct = 0.0
            direction = "fell" if prior_pct < 0 else "rose"
            return (
                None,
                0.45,
                f"CO2 releases to air: {'; '.join(f'{y}: {ghg_by_year[y]:,.1f} t' for y in years[-5:])}. "
                f"NOTE: The {years[-1]} figure ({last_val:,.1f} t) is >{last_val / penultimate:.0f}x the prior year "
                f"({years[-2]}: {penultimate:,.1f} t): likely a first-disclosure event (new facility or "
                f"pollutant type entering E-PRTR reporting scope), not a genuine emissions increase. "
                f"Excluding {years[-1]}: prior trend {direction} {abs(prior_pct):.0f}% "
                f"from {prior_years[0]} to {prior_years[-1]}. Treat {years[-1]} data with caution.",
            )

    first_year, first_val = years[0], vals[0]
    last_year, last_val = years[-1], vals[-1]

    if first_val == 0:
        return None, 0.4, "Baseline year has zero recorded emissions; trend unreliable."

    pct_change = (last_val - first_val) / first_val * 100

    if pct_change <= -30:
        return (
            True,
            0.75,
            f"CO2 releases fell {abs(pct_change):.0f}% from {first_year} to {last_year} "
            f"({first_val:,.1f} → {last_val:,.1f} t).",
        )
    if pct_change >= 20:
        return (
            False,
            0.75,
            f"CO2 releases rose {pct_change:.0f}% from {first_year} to {last_year} "
            f"({first_val:,.1f} → {last_val:,.1f} t).",
        )

    direction = "fell" if pct_change < 0 else "rose"
    return (
        None,
        0.55,
        f"CO2 releases {direction} {abs(pct_change):.0f}% from {first_year} to {last_year} "
        f"({first_val:,.1f} → {last_val:,.1f} t).",
    )

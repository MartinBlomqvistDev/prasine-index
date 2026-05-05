"""EEA National Emissions Inventories ingest module for the Prasine Index.

Loads the European Environment Agency (EEA) national greenhouse gas emissions
inventory (UNFCCC reporting) from the local bulk dataset downloaded via
scripts/refresh_eea_national.py.

This source provides country-level GHG totals and sector breakdowns reported
under the UNFCCC. It is the authoritative reference for:
  - Validating "X% of [country]'s emissions" claims
  - Checking whether a claimed sector reduction is credible against the national trend
  - Providing context on Sweden's / any EU country's total emissions trajectory

For greenwashing assessment:
  - If a company claims its project covers "X% of Sweden's emissions," the EEA
    national total allows arithmetic verification of that proportion.
  - Declining national trends do not excuse individual company inaction.
  - Rising national trends (e.g. energy sector rebound post-COVID) provide context.

Data source: EEA — national emissions reported to UNFCCC
  Dataset: eea_t_national-emissions-reported (UNFCCC reporting)
Refresh: python scripts/refresh_eea_national.py
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eea_national_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

_EEA_CSV: Path = Path(
    os.environ.get(
        "EEA_NATIONAL_CSV",
        str(
            _PROJECT_ROOT
            / "data"
            / "eea_t_national-emissions-reported_p_2025_v03_r00"
            / "UNFCCC_v28.csv"
        ),
    )
)

# UNFCCC sector codes for total national emissions (excl. LULUCF)
_TOTAL_SECTOR_CODE = "Sectors/Totals_excl"
_TOTAL_SECTOR_NAME = "Total emissions (UNFCCC)"
_GHG_ALL = "All greenhouse gases - (CO2 equivalent)"
_UNIT_GG_CO2 = "Gg CO2 equivalent"

# ISO 3166-1 alpha-2 → country name mapping for common EU countries
_COUNTRY_CODES: dict[str, str] = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MT": "Malta",
    "NL": "Netherlands",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
    "NO": "Norway",
    "IS": "Iceland",
    "LI": "Liechtenstein",
    "UK": "United Kingdom",
    "GB": "United Kingdom",
    "CH": "Switzerland",
}
_COUNTRY_NAMES_LOWER = {v.lower(): k for k, v in _COUNTRY_CODES.items()}

# Module-level cache: country_code -> year -> total_gg_co2e
_cache: dict[str, dict[int, float]] | None = None


def refresh_cache() -> None:
    """Reset the EEA national cache so the next call reloads from disk."""
    global _cache
    _cache = None
    logger.info("EEA national cache cleared.", extra={"operation": "eea_national_cache_reset"})


def _get_cache() -> dict[str, dict[int, float]]:
    global _cache

    if _cache is not None:
        return _cache

    if not _EEA_CSV.exists():
        _cache = {}
        logger.info(
            "EEA national data file not found — run scripts/refresh_eea_national.py. "
            f"Expected at: {_EEA_CSV}",
            extra={"operation": "eea_national_cache_missing"},
        )
        return _cache

    totals: dict[str, dict[int, float]] = {}

    with _EEA_CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            country_code = row.get("Country_code", "").strip().upper()
            pollutant = row.get("Pollutant_name", "").strip()
            sector_code = row.get("Sector_code", "").strip()
            unit = row.get("Unit", "").strip()
            emissions_str = row.get("emissions", "").strip()

            # Only total GHG in Gg CO2e
            if pollutant != _GHG_ALL:
                continue
            if sector_code != _TOTAL_SECTOR_CODE:
                continue
            if unit != _UNIT_GG_CO2:
                continue
            if not country_code or not emissions_str:
                continue

            try:
                year = int(row.get("Year", "0"))
                value = float(emissions_str)
            except ValueError:
                continue

            totals.setdefault(country_code, {})[year] = value

    _cache = totals

    country_count = len(totals)
    year_counts = {cc: len(years) for cc, years in totals.items()}
    max_years = max(year_counts.values()) if year_counts else 0
    logger.info(
        f"EEA national cache loaded: {country_count} countries, up to {max_years} years each",
        extra={"operation": "eea_national_cache_loaded"},
    )
    return _cache


def _resolve_country_code(company_country: str) -> str | None:
    """Resolve a company country string to ISO 2-letter code."""
    if not company_country:
        return None
    upper = company_country.strip().upper()
    if upper in _COUNTRY_CODES:
        return upper
    lower = company_country.strip().lower()
    return _COUNTRY_NAMES_LOWER.get(lower)


def _get_country_totals(country_code: str) -> dict[int, float]:
    cache = _get_cache()
    return cache.get(country_code, {})


def _extract_proportion_claim(claim_text: str) -> float | None:
    """Extract a percentage from a claim text, e.g. '10%' → 10.0."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", claim_text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


async def fetch_eea_national_data(claim: Claim, company: object) -> list[Evidence]:
    """Return EEA national emissions context for the company's home country.

    Provides national GHG totals to validate proportionality claims
    (e.g. "our project covers X% of Sweden's emissions") and sector trends.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A list with one Evidence record providing national emissions context,
        or empty if the company's country cannot be resolved or data is missing.
    """
    company_country: str = getattr(company, "country", "") or ""
    company_name: str = getattr(company, "name", "")

    country_code = _resolve_country_code(company_country)
    if not country_code:
        # Try to infer from claim or company name for Swedish companies
        claim_text = (getattr(claim, "raw_text", "") or "").lower()
        if any(kw in claim_text for kw in ("sweden", "sverige", "svensk", "helsingborg",
                                            "stockholm", "malmö", "gothenburg", "göteborg")):
            country_code = "SE"
        elif any(kw in claim_text for kw in ("norway", "norge", "norsk")):
            country_code = "NO"
        elif any(kw in claim_text for kw in ("germany", "deutschland", "german")):
            country_code = "DE"

    if not country_code:
        logger.info(
            f"EEA national: cannot resolve country for {company_name!r} "
            f"(country={company_country!r})",
            extra={"operation": "eea_national_no_country", "company": company_name},
        )
        return []

    totals = _get_country_totals(country_code)
    if not totals:
        logger.info(
            f"EEA national: no data for country {country_code}",
            extra={"operation": "eea_national_no_data", "country": country_code},
        )
        return []

    country_name = _COUNTRY_CODES.get(country_code, country_code)
    latest_year = max(totals)
    latest_total_gg = totals[latest_year]
    latest_total_mt = latest_total_gg / 1000

    # Check for a 1990 baseline to compute trend
    baseline_1990 = totals.get(1990)
    trend_str = ""
    if baseline_1990:
        change_pct = ((latest_total_gg - baseline_1990) / baseline_1990) * 100
        direction = "decreased" if change_pct < 0 else "increased"
        trend_str = (
            f" {country_name}'s total GHG emissions have {direction} "
            f"by {abs(change_pct):.1f}% since 1990 "
            f"(from {baseline_1990/1000:.1f} Mt CO2e in 1990 to "
            f"{latest_total_mt:.1f} Mt CO2e in {latest_year})."
        )

    # Check if the claim makes a country-proportion statement
    claim_text = getattr(claim, "raw_text", "") or ""
    proportion = _extract_proportion_claim(claim_text)
    proportion_str = ""
    if proportion is not None:
        implied_mt = latest_total_mt * proportion / 100
        proportion_str = (
            f" Claim implies {proportion:.0f}% of {country_name}'s emissions "
            f"≈ {implied_mt:.2f} Mt CO2e/year based on {latest_year} data."
        )

    summary = (
        f"EEA National Emissions Inventory: {country_name} total GHG emissions "
        f"(excl. LULUCF) were {latest_total_mt:.1f} Mt CO2e in {latest_year} "
        f"({latest_total_gg:,.0f} Gg CO2e), per UNFCCC reporting to EEA."
        f"{trend_str}{proportion_str} "
        f"This national baseline is used to verify proportionality claims."
    )

    logger.info(
        f"EEA national: {country_name} total {latest_total_mt:.1f} Mt CO2e ({latest_year})",
        extra={"operation": "eea_national_found", "country": country_code},
    )

    recent_years = {y: v for y, v in totals.items() if y >= latest_year - 5}

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.EEA_NATIONAL,
            evidence_type=EvidenceType.STATISTICAL,
            source_url="https://www.eea.europa.eu/en/datahub/datahubitem-view/3b313f97-7730-4b57-9ef4-4d4c38a82cfa",
            raw_data={
                "country_code": country_code,
                "country_name": country_name,
                "latest_year": latest_year,
                "total_gg_co2e": latest_total_gg,
                "total_mt_co2e": round(latest_total_mt, 3),
                "baseline_1990_gg": baseline_1990,
                "recent_years": recent_years,
            },
            summary=summary,
            data_year=latest_year,
            # National baseline is context, not directly supporting or contradicting
            supports_claim=None,
            confidence=0.95,
        )
    ]

"""Eurostat GHG emissions API ingest module for the Prasine Index.

Queries the Eurostat dissemination API (env_air_gge dataset) for country-level
and sector-level greenhouse gas emissions. No bulk download or registration
required — the API is free and publicly accessible.

Used to:
  - Provide a country GHG total cross-check against EEA national data
  - Break down emissions by sector (energy, industry, transport, agriculture)
    for validating "our sector is X% of national emissions" claims
  - Show the national emissions trend for context
  - Validate claimed sector-level reductions against official statistics

API reference:
  https://ec.europa.eu/eurostat/web/user-guides/data-browser/api-data-access/api-getting-started

Dataset: env_air_gge — GHG emissions by source sector (IPCC format)
Units: MIO_T (million tonnes CO2 equivalent)
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eurostat_data"]

logger = get_logger(__name__)

_BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/env_air_gge"

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "PrasineIndex/1.0 (EU greenwashing monitor)",
}

# Sectors to query — covers the full national inventory breakdown
_SECTORS: dict[str, str] = {
    "TOTX4_MEMO": "Total (excl. LULUCF)",
    "CRF1": "Energy",
    "CRF1A1": "Energy industries (power & heat)",
    "CRF1A2": "Manufacturing & construction",
    "CRF1A3": "Transport",
    "CRF2": "Industrial processes",
    "CRF3": "Agriculture",
    "CRF5": "Waste",
}

# ISO 3166-1 alpha-2 codes Eurostat accepts
_COUNTRY_CODES = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
    "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "RO", "SE", "SI", "SK", "NO", "IS", "CH",
    "UK", "GB",
})

_COUNTRY_NAMES_LOWER: dict[str, str] = {
    "austria": "AT", "belgium": "BE", "bulgaria": "BG", "croatia": "HR",
    "cyprus": "CY", "czechia": "CZ", "czech republic": "CZ", "denmark": "DK",
    "estonia": "EE", "finland": "FI", "france": "FR", "germany": "DE",
    "greece": "GR", "hungary": "HU", "ireland": "IE", "italy": "IT",
    "latvia": "LV", "lithuania": "LT", "luxembourg": "LU", "malta": "MT",
    "netherlands": "NL", "poland": "PL", "portugal": "PT", "romania": "RO",
    "slovakia": "SK", "slovenia": "SI", "spain": "ES", "sweden": "SE",
    "norway": "NO", "iceland": "IS", "switzerland": "CH",
    "united kingdom": "GB", "uk": "GB",
}

# In-process cache: country_code -> parsed sector/year data
_cache: dict[str, dict[str, dict[int, float]]] = {}

_SINCE_YEAR = 2018


def _resolve_country(company_country: str, claim_text: str) -> str | None:
    """Resolve company country string or claim keywords to a Eurostat geo code."""
    if not company_country:
        # Infer from claim text keywords
        text = claim_text.lower()
        kw_map = {
            "SE": ("sweden", "sverige", "svensk", "helsingborg", "stockholm", "malmö"),
            "NO": ("norway", "norge", "norsk"),
            "DE": ("germany", "deutschland", "german"),
            "FR": ("france", "français", "french"),
            "GB": ("uk", "britain", "british", "england"),
        }
        for code, keywords in kw_map.items():
            if any(kw in text for kw in keywords):
                return code
        return None

    upper = company_country.strip().upper()
    if upper in _COUNTRY_CODES:
        return upper if upper != "UK" else "GB"

    lower = company_country.strip().lower()
    return _COUNTRY_NAMES_LOWER.get(lower)


def _build_url(geo: str) -> str:
    params: list[tuple[str, str]] = [
        ("unit", "MIO_T"),
        ("airpol", "GHG"),
        ("geo", geo),
        ("sinceTimePeriod", str(_SINCE_YEAR)),
        ("format", "JSON"),
    ]
    for sector_code in _SECTORS:
        params.append(("src_crf", sector_code))
    return f"{_BASE_URL}?{urllib.parse.urlencode(params)}"


def _decode_response(data: dict[str, Any]) -> dict[str, dict[int, float]]:
    """Decode the Eurostat JSON-stat response into {sector_code: {year: value_mt}}.

    Eurostat returns a flat dict of integer indices mapping to float values.
    The index encodes position across all dimensions in order.
    For our query the dimension order is [freq, unit, airpol, src_crf, geo, time].
    """
    dims = data.get("dimension", {})
    sizes = data.get("size", [])
    values = data.get("value", {})
    dim_ids = data.get("id", [])

    if not dims or not sizes or not values:
        return {}

    # Build dimension index → label maps
    def _labels(dim_name: str) -> list[str]:
        dim = dims.get(dim_name, {})
        idx_map = dim.get("category", {}).get("index", {})
        label_map = dim.get("category", {}).get("label", {})
        if isinstance(idx_map, dict):
            # {code: position} — sort by position
            ordered = sorted(idx_map.items(), key=lambda x: x[1])
            return [k for k, _ in ordered]
        # If index is a list, it's already ordered
        return list(label_map.keys())

    src_crf_keys = _labels("src_crf")
    time_keys = _labels("time")

    # Calculate stride for each dimension
    # index = sum(dim_pos[i] * product(sizes[i+1:])) for all i
    strides: list[int] = []
    for i in range(len(sizes)):
        stride = 1
        for j in range(i + 1, len(sizes)):
            stride *= sizes[j]
        strides.append(stride)

    dim_name_to_idx = {name: i for i, name in enumerate(dim_ids)}
    src_crf_dim_idx = dim_name_to_idx.get("src_crf", 3)
    time_dim_idx = dim_name_to_idx.get("time", -1)

    result: dict[str, dict[int, float]] = {}

    for src_pos, sector_code in enumerate(src_crf_keys):
        sector_data: dict[int, float] = {}
        for time_pos, time_label in enumerate(time_keys):
            try:
                year = int(time_label)
            except ValueError:
                continue

            # Build the flat index
            flat_idx = src_pos * strides[src_crf_dim_idx] + time_pos * strides[time_dim_idx]
            val = values.get(str(flat_idx))
            if val is not None:
                sector_data[year] = float(val)

        if sector_data:
            result[sector_code] = sector_data

    return result


def _fetch_sync(geo: str) -> dict[str, dict[int, float]]:
    """Synchronous HTTP fetch — run via asyncio.to_thread."""
    url = _build_url(geo)
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return _decode_response(data)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning(
            f"Eurostat API fetch failed for geo={geo}: {exc}",
            extra={"operation": "eurostat_fetch_error", "geo": geo},
        )
        return {}


async def fetch_eurostat_data(claim: Claim, company: object) -> list[Evidence]:
    """Return Eurostat GHG sector breakdown for the company's country.

    Queries the Eurostat env_air_gge dataset for total and sector-level GHG
    emissions. Provides the national context needed to validate sector-proportion
    claims and benchmark the company's stated emissions trajectory against
    official statistics.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if the country cannot
        be resolved or the API call fails.
    """
    company_country: str = getattr(company, "country", "") or ""
    company_name: str = getattr(company, "name", "")
    claim_text: str = getattr(claim, "raw_text", "") or ""

    geo = _resolve_country(company_country, claim_text)
    if not geo:
        logger.info(
            f"Eurostat: cannot resolve country for {company_name!r} "
            f"(country={company_country!r})",
            extra={"operation": "eurostat_no_country", "company": company_name},
        )
        return []

    # Use in-process cache
    if geo not in _cache:
        logger.info(
            f"Eurostat: fetching GHG data for {geo}",
            extra={"operation": "eurostat_fetch", "geo": geo},
        )
        sector_data = await asyncio.to_thread(_fetch_sync, geo)
        if not sector_data:
            return []
        _cache[geo] = sector_data
    else:
        sector_data = _cache[geo]

    # Extract total and latest year
    total_data = sector_data.get("TOTX4_MEMO", {})
    if not total_data:
        return []

    latest_year = max(total_data)
    total_mt = total_data[latest_year]

    summary = _build_summary(geo, company_name, sector_data, latest_year, total_mt, claim_text)

    logger.info(
        f"Eurostat: {geo} total {total_mt:.1f} Mt CO2e ({latest_year}), "
        f"{len(sector_data)} sectors",
        extra={"operation": "eurostat_found", "geo": geo},
    )

    # Build sector breakdown for raw_data
    sector_breakdown: dict[str, dict[str, float]] = {}
    for sector_code, year_data in sector_data.items():
        sector_label = _SECTORS.get(sector_code, sector_code)
        latest = max(year_data) if year_data else None
        if latest:
            sector_breakdown[sector_label] = {
                str(y): v for y, v in sorted(year_data.items())
            }

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.EUROSTAT,
            evidence_type=EvidenceType.STATISTICAL,
            source_url=f"https://ec.europa.eu/eurostat/databrowser/view/env_air_gge/default/table?lang=en&geo={geo}",
            raw_data={
                "geo": geo,
                "latest_year": latest_year,
                "total_mt_co2e": round(total_mt, 3),
                "sector_breakdown_mt": sector_breakdown,
            },
            summary=summary,
            data_year=latest_year,
            supports_claim=None,
            confidence=0.95,
        )
    ]


def _build_summary(
    geo: str,
    company_name: str,
    sector_data: dict[str, dict[int, float]],
    latest_year: int,
    total_mt: float,
    claim_text: str,
) -> str:
    lines = [
        f"Eurostat env_air_gge: {geo} total GHG emissions (excl. LULUCF) "
        f"were {total_mt:.1f} Mt CO2e in {latest_year}."
    ]

    # Trend from first available year
    total_series = sector_data.get("TOTX4_MEMO", {})
    if len(total_series) > 1:
        first_year = min(total_series)
        first_val = total_series[first_year]
        change_pct = ((total_mt - first_val) / first_val) * 100
        direction = "decreased" if change_pct < 0 else "increased"
        lines.append(
            f"Trend: emissions {direction} {abs(change_pct):.1f}% "
            f"from {first_val:.1f} Mt in {first_year} to {total_mt:.1f} Mt in {latest_year}."
        )

    # Key sectors as % of total
    sector_pcts: list[str] = []
    for code, label in _SECTORS.items():
        if code == "TOTX4_MEMO":
            continue
        series = sector_data.get(code, {})
        if latest_year in series and total_mt > 0:
            pct = (series[latest_year] / total_mt) * 100
            sector_pcts.append(f"{label} {pct:.1f}%")
    if sector_pcts:
        lines.append(f"Sector shares ({latest_year}): {'; '.join(sector_pcts)}.")

    # Proportion check if claim mentions a percentage
    import re
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", claim_text)
    if m:
        claimed_pct = float(m.group(1).replace(",", "."))
        implied_mt = total_mt * claimed_pct / 100
        lines.append(
            f"Claim implies {claimed_pct:.0f}% of {geo} national total "
            f"≈ {implied_mt:.2f} Mt CO2e ({latest_year} baseline)."
        )

    return " ".join(lines)

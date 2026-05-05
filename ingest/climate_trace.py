"""Climate TRACE API ingest module for the Prasine Index.

Queries the Climate TRACE v7 REST API for independent satellite/ML-derived
emissions estimates. No authentication or registration required.

Climate TRACE is the only source in the pipeline that provides emissions
estimates that are entirely independent of company self-reporting. Estimates
are produced using remote sensing, satellite imagery, financial data, and
machine learning — not regulatory filings or voluntary disclosure.

This makes it the primary fallback when EU ETS has no registered installations
for a company (e.g. smaller utilities, regional energy companies like Öresundskraft).

Two queries per run:
  1. /v7/sources — find installations for the specific company by name matching.
     Returns facility-level independently estimated emissions.
  2. /v7/sources/emissions — country-level aggregate for context
     (cross-checks Eurostat and EEA national data).

A discrepancy between Climate TRACE estimates and a company's self-reported
figures is a strong greenwashing signal — one of the few sources that can
contradict a company's own disclosure with independent evidence.

API reference: https://api.climatetrace.org/v7/swagger/index.html
Data coverage: 2015 to present (country aggregates); 2021 to present (sources)
Units: tonnes CO2e (100-year GWP)
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, cast

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_climate_trace_data"]

logger = get_logger(__name__)

_BASE = "https://api.climatetrace.org/v7"

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "PrasineIndex/1.0 (EU greenwashing monitor)",
}

# ISO alpha-3 codes Climate TRACE uses for gadmId (country level)
_ISO2_TO_ISO3: dict[str, str] = {
    "AT": "AUT", "BE": "BEL", "BG": "BGR", "CY": "CYP", "CZ": "CZE",
    "DE": "DEU", "DK": "DNK", "EE": "EST", "ES": "ESP", "FI": "FIN",
    "FR": "FRA", "GR": "GRC", "HR": "HRV", "HU": "HUN", "IE": "IRL",
    "IT": "ITA", "LT": "LTU", "LU": "LUX", "LV": "LVA", "MT": "MLT",
    "NL": "NLD", "PL": "POL", "PT": "PRT", "RO": "ROU", "SE": "SWE",
    "SI": "SVN", "SK": "SVK", "NO": "NOR", "IS": "ISL", "CH": "CHE",
    "GB": "GBR", "UK": "GBR",
}

_COUNTRY_NAMES_LOWER: dict[str, str] = {
    "sweden": "SWE", "germany": "DEU", "france": "FRA", "norway": "NOR",
    "denmark": "DNK", "finland": "FIN", "netherlands": "NLD", "poland": "POL",
    "spain": "ESP", "italy": "ITA", "austria": "AUT", "belgium": "BEL",
    "united kingdom": "GBR", "uk": "GBR", "switzerland": "CHE",
    "czechia": "CZE", "czech republic": "CZE", "portugal": "PRT",
}

# In-process cache: (gadm_id, company_norm) -> list[dict]
_source_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
_aggregate_cache: dict[str, dict[str, Any]] = {}

# Max sources to fetch per country search — keeps API calls bounded
_MAX_SOURCES = 300


def _resolve_gadm(company_country: str, claim_text: str) -> str | None:
    if company_country:
        upper = company_country.strip().upper()
        if upper in _ISO2_TO_ISO3:
            return _ISO2_TO_ISO3[upper]
        # Already ISO-3?
        if len(upper) == 3 and upper in _ISO2_TO_ISO3.values():
            return upper

    text = (claim_text or "").lower()
    for name, gadm in _COUNTRY_NAMES_LOWER.items():
        if name in text:
            return gadm

    return None


def _normalise(name: str) -> str:
    return name.lower().strip()


def _name_matches(company_norm: str, source_name: str) -> bool:
    """Check if the company name appears in or substantially overlaps a source name."""
    src_norm = _normalise(source_name)
    # Direct substring
    if company_norm in src_norm or src_norm in company_norm:
        return True
    # First word match (catches "Shell" in "Shell Pernis refinery")
    company_first = company_norm.split()[0] if company_norm.split() else company_norm
    return len(company_first) >= 4 and company_first in src_norm


def _fetch_sources_sync(gadm_id: str, company_norm: str) -> list[dict[str, Any]]:
    """Fetch top sources for a country and filter by company name."""
    params = urllib.parse.urlencode([
        ("year", "2023"),
        ("gas", "co2e_100yr"),
        ("gadmId", gadm_id),
        ("limit", str(_MAX_SOURCES)),
    ])
    url = f"{_BASE}/sources?{params}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning(
            f"Climate TRACE sources fetch failed: {exc}",
            extra={"operation": "climate_trace_sources_error"},
        )
        return []

    if not isinstance(data, list):
        return []

    return [src for src in data if _name_matches(company_norm, src.get("name", ""))]


def _fetch_aggregate_sync(gadm_id: str) -> dict[str, Any]:
    """Fetch country-level aggregate emissions."""
    params = urllib.parse.urlencode([
        ("year", "2023"),
        ("gas", "co2e_100yr"),
        ("gadmId", gadm_id),
        ("sectors", "all_no_forest"),
    ])
    url = f"{_BASE}/sources/emissions?{params}"

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return cast("dict[str, Any]", json.loads(resp.read().decode("utf-8")))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        logger.warning(
            f"Climate TRACE aggregate fetch failed: {exc}",
            extra={"operation": "climate_trace_aggregate_error"},
        )
        return {}


async def fetch_climate_trace_data(claim: Claim, company: object) -> list[Evidence]:
    """Return Climate TRACE independent emissions estimates for a company.

    Queries two endpoints:
    1. Installation-level search — finds specific facilities attributed to
       the company by name matching. These are independently estimated, not
       self-reported. A mismatch with company-claimed figures is a strong signal.
    2. Country aggregate — provides the national total context for the
       company's country (cross-checks Eurostat and EEA national data).

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        Up to two Evidence records: one for matched installations (if found)
        and one for the country aggregate context.
    """
    company_name: str = getattr(company, "name", "")
    company_country: str = getattr(company, "country", "") or ""
    claim_text: str = getattr(claim, "raw_text", "") or ""

    gadm_id = _resolve_gadm(company_country, claim_text)
    if not gadm_id:
        logger.info(
            f"Climate TRACE: cannot resolve country for {company_name!r}",
            extra={"operation": "climate_trace_no_country"},
        )
        return []

    company_norm = _normalise(company_name)
    results: list[Evidence] = []

    # --- Query 1: installation-level match ---
    cache_key = (gadm_id, company_norm)
    if cache_key not in _source_cache:
        matched = await asyncio.to_thread(_fetch_sources_sync, gadm_id, company_norm)
        _source_cache[cache_key] = matched
    else:
        matched = _source_cache[cache_key]

    if matched:
        total_emissions_t = sum(s.get("emissionsQuantity", 0) for s in matched)
        total_emissions_mt = total_emissions_t / 1_000_000

        installations_str = "; ".join(
            f"{s['name']} ({s.get('subsector', s.get('sector', '?'))}: "
            f"{s.get('emissionsQuantity', 0)/1000:.0f} kt CO2e)"
            for s in matched[:5]
        )
        summary = (
            f"Climate TRACE independent estimate: {len(matched)} installation(s) "
            f"attributed to {company_name!r} in {gadm_id}, total "
            f"{total_emissions_mt:.3f} Mt CO2e (2023, 100yr GWP). "
            f"Installations: {installations_str}. "
            f"These estimates are derived from satellite imagery, remote sensing, "
            f"and ML — independent of company self-reporting. A significant "
            f"discrepancy with company-disclosed figures constitutes a primary "
            f"greenwashing signal."
        )

        logger.info(
            f"Climate TRACE: {len(matched)} installations matched for "
            f"{company_name!r} in {gadm_id}, total {total_emissions_mt:.3f} Mt",
            extra={"operation": "climate_trace_match", "company": company_name},
        )

        results.append(
            Evidence(
                claim_id=claim.id,
                trace_id=claim.trace_id,
                source=EvidenceSource.CLIMATE_TRACE,
                evidence_type=EvidenceType.VERIFIED_EMISSIONS,
                source_url=f"https://climatetrace.org/explore#?country={gadm_id}",
                raw_data={
                    "gadm_id": gadm_id,
                    "company": company_name,
                    "installations_found": len(matched),
                    "total_emissions_t_co2e": round(total_emissions_t, 2),
                    "total_emissions_mt_co2e": round(total_emissions_mt, 6),
                    "installations": [
                        {
                            "id": s.get("id"),
                            "name": s.get("name"),
                            "sector": s.get("sector"),
                            "subsector": s.get("subsector"),
                            "emissions_t": round(s.get("emissionsQuantity", 0), 2),
                        }
                        for s in matched[:10]
                    ],
                },
                summary=summary,
                data_year=2023,
                supports_claim=None,
                confidence=0.75,
            )
        )
    else:
        logger.info(
            f"Climate TRACE: no installations matched for {company_name!r} in {gadm_id}",
            extra={"operation": "climate_trace_no_match", "company": company_name},
        )

    # --- Query 2: country aggregate ---
    if gadm_id not in _aggregate_cache:
        agg = await asyncio.to_thread(_fetch_aggregate_sync, gadm_id)
        _aggregate_cache[gadm_id] = agg
    else:
        agg = _aggregate_cache[gadm_id]

    if agg:
        total_summaries = agg.get("totals", {}).get("summaries", [])
        total_t = next(
            (s["emissionsQuantity"] for s in total_summaries if s.get("gas") == "co2e_100yr"),
            None,
        )

        if total_t is not None:
            total_mt = total_t / 1_000_000
            sector_summaries = agg.get("sectors", {}).get("summaries", [])
            sector_lines = [
                f"{s['sector']} {s.get('percentage', 0):.1f}%"
                for s in sorted(
                    sector_summaries, key=lambda x: x.get("emissionsQuantity", 0), reverse=True
                )[:5]
                if s.get("gas") == "co2e_100yr"
            ]

            agg_summary = (
                f"Climate TRACE country aggregate ({gadm_id}, 2023, all sectors excl. "
                f"forestry): {total_mt:.1f} Mt CO2e. "
                f"Top sectors: {'; '.join(sector_lines) if sector_lines else 'not available'}. "
                f"Climate TRACE uses independent satellite/ML estimates — "
                f"compare against Eurostat/EEA official figures for consistency."
            )

            results.append(
                Evidence(
                    claim_id=claim.id,
                    trace_id=claim.trace_id,
                    source=EvidenceSource.CLIMATE_TRACE,
                    evidence_type=EvidenceType.STATISTICAL,
                    source_url=f"https://climatetrace.org/explore#?country={gadm_id}",
                    raw_data={
                        "gadm_id": gadm_id,
                        "type": "country_aggregate",
                        "total_mt_co2e": round(total_mt, 3),
                        "sector_breakdown": sector_summaries[:10],
                    },
                    summary=agg_summary,
                    data_year=2023,
                    supports_claim=None,
                    confidence=0.80,
                )
            )

    return results

"""EU ETS ingest module for the Prasine Index Verification Agent.

Loads verified annual emissions from the official EU Union Registry daily CSV
snapshot (EUTL24/operators_yearly_activity_daily.csv), which is sourced from
union-registry-data.ec.europa.eu and updated daily. Falls back to the euets.info
CSV snapshot (eutl_2024_202410/compliance.csv) if the daily file is absent.

EU ETS data is the highest-quality evidence in the pipeline: verified by
accredited third parties, mandated by EU Regulation 601/2012, and published
annually. Rising verified emissions while a company claims reductions is the
most direct greenwashing signal available.

Installation IDs stored in the database use the euets.info convention
(e.g. "IE_201078"). The official registry CSV uses numeric-only IDs (201078).
This module handles both formats transparently.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eu_ets_data", "refresh_cache"]

logger = get_logger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent

# Primary: official EU Union Registry daily snapshot
_EUTL_DAILY_CSV: Path = Path(
    os.environ.get(
        "EUTL_DAILY_CSV",
        str(_PROJECT_ROOT / "EUTL24" / "operators_yearly_activity_daily.csv"),
    )
)

# Fallback: euets.info static snapshot (October 2024, covers up to 2023)
_EUTL_LEGACY_CSV: Path = Path(
    os.environ.get(
        "EUTL_LEGACY_CSV",
        str(_PROJECT_ROOT / "eutl_2024_202410" / "compliance.csv"),
    )
)

# Number of most recent years to include in the trend summary.
_YEARS_TO_RETRIEVE: int = 5

# Module-level cache: {numeric_installation_id: [(year, emissions_tco2e), ...]} asc by year.
_emissions_cache: dict[int, list[tuple[int, float]]] | None = None


def _parse_installation_id(raw_id: str) -> int | None:
    """Convert an installation ID in any supported format to its numeric form.

    Accepts:
    - Numeric string: "201078" → 201078
    - euets.info prefixed: "IE_201078" → 201078

    Args:
        raw_id: Installation ID as stored in Company.eu_ets_installation_ids.

    Returns:
        Integer numeric ID, or None if unparseable.
    """
    raw_id = raw_id.strip()
    if "_" in raw_id:
        raw_id = raw_id.split("_", 1)[1]
    try:
        return int(raw_id)
    except ValueError:
        return None


def _load_daily_cache() -> dict[int, list[tuple[int, float]]]:
    """Parse operators_yearly_activity_daily.csv into the emissions lookup.

    Skips rows where VERIFIED_EMISSIONS is -1 (no data / not in scope for
    that year). Returns a mapping from numeric installation ID to a list of
    (year, tCO2e) tuples sorted ascending by year.
    """
    path = _EUTL_DAILY_CSV
    if not path.exists():
        return {}

    data: dict[int, list[tuple[int, float]]] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            raw_verified = row.get("VERIFIED_EMISSIONS", "").strip()
            if not raw_verified:
                continue
            try:
                emissions = float(raw_verified)
            except ValueError:
                continue
            if emissions < 0:
                continue  # -1 sentinel means no data
            try:
                inst_id = int(row["INSTALLATION_IDENTIFIER"])
                year = int(row["PERIOD_YEAR"])
            except (ValueError, KeyError):
                continue
            data.setdefault(inst_id, []).append((year, emissions))

    for inst_id in data:
        data[inst_id].sort(key=lambda t: t[0])

    return data


def _load_legacy_cache() -> dict[int, list[tuple[int, float]]]:
    """Parse compliance.csv (euets.info format) into the emissions lookup.

    Filters to reportedInSystem_id == 'euets' and converts the prefixed
    installation IDs (e.g. IE_201078) to numeric form for a uniform cache key.
    """
    path = _EUTL_LEGACY_CSV
    if not path.exists():
        return {}

    data: dict[int, list[tuple[int, float]]] = {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("reportedInSystem_id") != "euets":
                continue
            raw_verified = row.get("verified", "").strip()
            if not raw_verified:
                continue
            try:
                emissions = float(raw_verified)
                year = int(row["year"])
            except (ValueError, KeyError):
                continue
            numeric_id = _parse_installation_id(row.get("installation_id", ""))
            if numeric_id is None:
                continue
            data.setdefault(numeric_id, []).append((year, emissions))

    for inst_id in data:
        data[inst_id].sort(key=lambda t: t[0])

    return data


def refresh_cache() -> None:
    """Reset the module-level emissions cache so the next call reloads from disk.

    Call this after running scripts/refresh_eutl.py to ensure the pipeline
    picks up newly downloaded data without restarting the process.
    """
    global _emissions_cache
    _emissions_cache = None
    logger.info("EU ETS cache cleared; will reload on next call.", extra={"operation": "eu_ets_cache_reset"})


def _get_cache() -> dict[int, list[tuple[int, float]]]:
    """Return the module-level emissions cache, loading it on first call.

    Prefers the daily official registry snapshot; falls back to the legacy
    euets.info CSV if the daily file is absent.
    """
    global _emissions_cache
    if _emissions_cache is not None:
        return _emissions_cache

    if _EUTL_DAILY_CSV.exists():
        _emissions_cache = _load_daily_cache()
        logger.info(
            f"EU ETS cache loaded from daily snapshot: {len(_emissions_cache)} installations",
            extra={"operation": "eu_ets_cache_loaded", "source": "daily"},
        )
    else:
        _emissions_cache = _load_legacy_cache()
        logger.info(
            f"EU ETS cache loaded from legacy snapshot: {len(_emissions_cache)} installations",
            extra={"operation": "eu_ets_cache_loaded", "source": "legacy"},
        )

    return _emissions_cache


async def fetch_eu_ets_data(
    claim: Claim,
    installation_ids: list[str],
) -> list[Evidence]:
    """Return verified annual emissions evidence for a company's EU ETS installations.

    Looks up each installation in the local emissions cache (no network I/O).
    Installations with no data in the snapshot are skipped with an info log.

    Args:
        claim: The claim under assessment. Provides trace_id and claim_id
            for constructing Evidence records.
        installation_ids: EU ETS installation identifiers from
            Company.eu_ets_installation_ids (euets.info format e.g. "IE_201078"
            or plain numeric "201078").

    Returns:
        List of Evidence records, one per installation with data.
    """
    if not installation_ids:
        logger.info(
            "No EU ETS installation IDs provided; skipping.",
            extra={"operation": "eu_ets_no_ids"},
        )
        return []

    cache = _get_cache()
    evidence_records: list[Evidence] = []

    for raw_id in installation_ids:
        numeric_id = _parse_installation_id(raw_id)
        if numeric_id is None:
            logger.warning(
                f"Could not parse installation ID: {raw_id}",
                extra={"operation": "eu_ets_bad_id"},
            )
            continue
        record = _build_evidence(
            claim=claim,
            display_id=raw_id,
            history=cache.get(numeric_id, []),
        )
        if record is not None:
            evidence_records.append(record)

    if not evidence_records:
        logger.warning(
            f"No EU ETS data found for installations: {installation_ids}",
            extra={"operation": "eu_ets_no_data_any"},
        )

    return evidence_records


def _build_evidence(
    claim: Claim,
    display_id: str,
    history: list[tuple[int, float]],
) -> Evidence | None:
    """Build an Evidence record from a single installation's emissions history.

    Args:
        claim: The claim under assessment.
        display_id: Installation ID as it appears in the company record.
        history: (year, tCO2e) tuples sorted ascending by year.

    Returns:
        An Evidence record, or None if history is empty.
    """
    if not history:
        logger.info(
            f"EU ETS: no data for installation {display_id}",
            extra={"operation": "eu_ets_install_no_data"},
        )
        return None

    most_recent_year, most_recent_emissions = history[-1]
    oldest_year, oldest_emissions = history[0]

    # Full history for Judge — critical for long-period claims ("since 2006").
    # Show all years if ≤12, otherwise show oldest + most recent N years.
    if len(history) <= 12:
        display_history = history
    else:
        display_history = history[:2] + [(-1, -1)] + history[-(_YEARS_TO_RETRIEVE):]

    trend_lines: list[str] = []
    for yr, em in display_history:
        if yr == -1:
            trend_lines.append("...")
        else:
            trend_lines.append(f"{yr}: {em:,.0f} tCO2e")
    trend_summary = " | ".join(trend_lines)

    supports_claim, confidence = _assess_emissions_vs_claim(
        claim_text=claim.raw_text,
        history=history,
    )

    # Directional framing for the Judge.
    if len(history) >= 2:
        pct_change = ((most_recent_emissions - oldest_emissions) / oldest_emissions * 100) if oldest_emissions else 0
        direction = f"{'DOWN' if pct_change < 0 else 'UP'} {abs(pct_change):.0f}% from {oldest_year} to {most_recent_year}"
    else:
        direction = "insufficient data for trend"

    summary = (
        f"EU ETS verified emissions for installation {display_id}: "
        f"{most_recent_emissions:,.0f} tCO2e in {most_recent_year} "
        f"(trend: {direction}). "
        f"Full history: {trend_summary}."
    )

    return Evidence(
        claim_id=claim.id,
        trace_id=claim.trace_id,
        source=EvidenceSource.EU_ETS,
        evidence_type=EvidenceType.VERIFIED_EMISSIONS,
        source_url=f"https://union-registry-data.ec.europa.eu/report/welcome",
        raw_data={
            "installation_id": display_id,
            "verified_emissions": [
                {"year": yr, "verifiedEmissions": em} for yr, em in history
            ],
            "data_source": "EU Union Registry daily snapshot",
            "most_recent_year": most_recent_year,
        },
        summary=summary,
        data_year=most_recent_year,
        supports_claim=supports_claim,
        confidence=confidence,
    )


def _assess_emissions_vs_claim(
    claim_text: str,
    history: list[tuple[int, float]],
) -> tuple[bool | None, float]:
    """Heuristically assess whether EU ETS emissions data supports the claim.

    Args:
        claim_text: The verbatim claim text.
        history: (year, tCO2e) tuples sorted ascending.

    Returns:
        Tuple of (supports_claim, confidence).
    """
    claim_lower = claim_text.lower()
    reduction_keywords = (
        "reduc", "decreas", "lower", "cut", "decarboni", "net zero", "carbon neutral",
    )
    is_reduction_claim = any(kw in claim_lower for kw in reduction_keywords)

    if len(history) < 2:
        return None, 0.5

    # For reduction/decarbonisation claims, use the FULL history to detect
    # long-period trends (e.g. "reduced 87% since 2006"). Recent 3-year window
    # is only used if the full history is short (≤4 years).
    if len(history) > 4:
        oldest_em = history[0][1]
        newest_em = history[-1][1]
    else:
        oldest_em = history[0][1]
        newest_em = history[-1][1]

    trend_up = newest_em > oldest_em * 1.05    # >5% increase = meaningful up
    trend_down = newest_em < oldest_em * 0.95  # >5% decrease = meaningful down

    if is_reduction_claim:
        if trend_down:
            return True, 0.75
        if trend_up:
            return False, 0.75
        return None, 0.6

    return None, 0.5

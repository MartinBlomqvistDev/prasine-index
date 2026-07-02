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
import datetime as _dt
import os
import re
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

# Module-level cache keyed by (registry_code, numeric_id) — installation
# numbers are only unique WITHIN a national registry (1,271 numeric IDs occur
# in more than one country in the 2026 daily snapshot), so an unscoped key
# would silently merge emissions from unrelated installations across borders.
_emissions_cache: dict[tuple[str, int], list[tuple[int, float]]] | None = None


def _parse_installation_id(raw_id: str) -> tuple[str | None, int] | None:
    """Split an installation ID into (registry_code, numeric_id).

    Accepts:
    - Prefixed (euets.info convention): "SE_495" → ("SE", 495)
    - Plain numeric: "495" → (None, 495) — resolvable only if the number is
      unambiguous across registries.

    Args:
        raw_id: Installation ID as stored in Company.eu_ets_installation_ids.

    Returns:
        Tuple of (registry_code | None, numeric_id), or None if unparseable.
    """
    raw_id = raw_id.strip()
    registry: str | None = None
    if "_" in raw_id:
        registry, raw_id = raw_id.split("_", 1)
        registry = registry.strip().upper() or None
    try:
        return registry, int(raw_id)
    except ValueError:
        return None


def _load_daily_cache() -> dict[tuple[str, int], list[tuple[int, float]]]:
    """Parse operators_yearly_activity_daily.csv into the emissions lookup.

    Skips rows where VERIFIED_EMISSIONS is -1 (no data / not in scope for
    that year). Returns a mapping from numeric installation ID to a list of
    (year, tCO2e) tuples sorted ascending by year.
    """
    path = _EUTL_DAILY_CSV
    if not path.exists():
        return {}

    data: dict[tuple[str, int], list[tuple[int, float]]] = {}
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
                registry = row["REGISTRY_CODE"].strip().upper()
            except (ValueError, KeyError):
                continue
            data.setdefault((registry, inst_id), []).append((year, emissions))

    for key in data:
        data[key].sort(key=lambda t: t[0])

    return data


def _load_legacy_cache() -> dict[tuple[str, int], list[tuple[int, float]]]:
    """Parse compliance.csv (euets.info format) into the emissions lookup.

    Filters to reportedInSystem_id == 'euets' and converts the prefixed
    installation IDs (e.g. IE_201078) to (registry, numeric) cache keys.
    """
    path = _EUTL_LEGACY_CSV
    if not path.exists():
        return {}

    data: dict[tuple[str, int], list[tuple[int, float]]] = {}
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
            parsed = _parse_installation_id(row.get("installation_id", ""))
            if parsed is None or parsed[0] is None:
                continue  # legacy rows must carry the registry prefix
            data.setdefault((parsed[0], parsed[1]), []).append((year, emissions))

    for key in data:
        data[key].sort(key=lambda t: t[0])

    return data


def refresh_cache() -> None:
    """Reset the module-level emissions cache so the next call reloads from disk.

    Call this after running scripts/refresh_eutl.py to ensure the pipeline
    picks up newly downloaded data without restarting the process.
    """
    global _emissions_cache
    _emissions_cache = None
    logger.info(
        "EU ETS cache cleared; will reload on next call.", extra={"operation": "eu_ets_cache_reset"}
    )


def _get_cache() -> dict[tuple[str, int], list[tuple[int, float]]]:
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
        parsed = _parse_installation_id(raw_id)
        if parsed is None:
            logger.warning(
                f"Could not parse installation ID: {raw_id}",
                extra={"operation": "eu_ets_bad_id"},
            )
            continue
        registry, numeric_id = parsed
        if registry is not None:
            history = cache.get((registry, numeric_id), [])
        else:
            # Unprefixed ID: usable only if the number is unique across
            # registries — otherwise we cannot know which installation is
            # meant and must not guess.
            candidates = [k for k in cache if k[1] == numeric_id]
            if len(candidates) > 1:
                logger.warning(
                    f"Installation ID {raw_id} is ambiguous across "
                    f"{len(candidates)} registries — store it with a registry "
                    "prefix (e.g. SE_495) to resolve. Skipping.",
                    extra={"operation": "eu_ets_ambiguous_id"},
                )
                continue
            history = cache.get(candidates[0], []) if candidates else []
        record = _build_evidence(
            claim=claim,
            display_id=raw_id,
            history=history,
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
    oldest_year, _oldest_emissions = history[0]

    # Full history for Judge — critical for long-period claims ("since 2006").
    # Show all years if ≤12, otherwise show oldest + most recent N years.
    if len(history) <= 12:
        display_history = history
    else:
        display_history = [*history[:2], (-1, -1), *history[-(_YEARS_TO_RETRIEVE):]]

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

    # Directional framing for the Judge. The headline trend is computed from
    # 2013 (EU ETS phase 3) onward when possible: phase 1–2 years (2005–2012)
    # had narrower activity/gas scope, so a 2005 baseline can show a large
    # "increase" that is a reporting-scope artefact, not real emissions growth.
    # The full history (including pre-2013 years) is still shown alongside.
    trend_base = [(y, e) for y, e in history if y >= 2013] or history
    base_year, base_emissions = trend_base[0]
    if len(history) >= 2 and base_year != most_recent_year:
        pct_change = (
            ((most_recent_emissions - base_emissions) / base_emissions * 100)
            if base_emissions
            else 0
        )
        direction = (
            f"{'DOWN' if pct_change < 0 else 'UP'} {abs(pct_change):.0f}% "
            f"from {base_year} to {most_recent_year}"
        )
        if base_year != oldest_year:
            direction += " (trend baseline 2013 — earlier ETS phases had narrower reporting scope)"
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
        source_url="https://union-registry-data.ec.europa.eu/report/welcome",
        raw_data={
            "installation_id": display_id,
            "verified_emissions": [{"year": yr, "verifiedEmissions": em} for yr, em in history],
            "data_source": "EU Union Registry daily snapshot",
            "most_recent_year": most_recent_year,
        },
        summary=summary,
        data_year=most_recent_year,
        supports_claim=supports_claim,
        confidence=confidence,
    )


def _extract_claim_years(claim_text: str) -> tuple[int | None, int | None]:
    """Extract baseline and target years from a claim text.

    Scans for four-digit years in the plausible range 1990–2100. Years in the
    past (≤ current year) are treated as baseline years; years in the future
    are treated as target years. When multiple past or future years appear, the
    earliest past year is the baseline and the latest future year is the target.

    Args:
        claim_text: The verbatim claim text.

    Returns:
        Tuple of (baseline_year, target_year), either of which may be None.
    """
    current_year = _dt.datetime.now().year
    all_years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", claim_text)]
    past_years = sorted(y for y in all_years if 1990 <= y <= current_year)
    future_years = sorted(y for y in all_years if current_year < y <= 2100)
    baseline = past_years[0] if past_years else None
    target = future_years[-1] if future_years else None
    return baseline, target


def _assess_emissions_vs_claim(
    claim_text: str,
    history: list[tuple[int, float]],
) -> tuple[bool | None, float]:
    """Heuristically assess whether EU ETS emissions data supports the claim.

    EU ETS only tracks absolute verified emissions. Pure intensity claims (e.g.
    "CO2 per tonne of product") cannot be assessed from this data — the function
    abstains rather than returning a misleading high-confidence contradiction.

    When the claim names a specific baseline year (e.g. "reduced 87% since 2006"),
    the comparison is anchored to that year rather than the oldest record. For
    future targets (e.g. "net zero by 2050"), the recent 3-year emissions slope
    is extrapolated to check whether the trajectory is consistent with the target.

    Args:
        claim_text: The verbatim claim text.
        history: (year, tCO2e) tuples sorted ascending.

    Returns:
        Tuple of (supports_claim, confidence). Returns (None, 0.5) for intensity
        claims or when history is insufficient.
    """
    claim_lower = claim_text.lower()

    # EU ETS tracks absolute figures only. Pure intensity claims ("CO2 per tonne
    # of product") must be abstained from — absolute trend direction is
    # meaningless and produces high-confidence wrong signals for heavy industry
    # (cement, steel) with growing production volumes.
    # Compound claims that include both intensity AND absolute/net-zero language
    # are assessed normally: the absolute trajectory is still relevant for the
    # net-zero component even if the intensity sub-target cannot be verified.
    intensity_keywords = (
        "per tonne",
        "per unit",
        "per product",
        "per kwh",
        "per mwh",
        "intensity",
        "specific emission",
        "emission factor",
        "carbon intensity",
        "emissions intensity",
    )
    absolute_keywords = ("net zero", "carbon neutral", "climate neutral", "zero emission")
    if any(kw in claim_lower for kw in intensity_keywords) and not any(
        kw in claim_lower for kw in absolute_keywords
    ):
        return None, 0.5

    reduction_keywords = (
        "reduc",
        "decreas",
        "lower",
        "cut",
        "decarboni",
        "net zero",
        "carbon neutral",
    )
    is_reduction_claim = any(kw in claim_lower for kw in reduction_keywords)

    if len(history) < 2:
        return None, 0.5

    baseline_year, target_year = _extract_claim_years(claim_text)
    history_dict = dict(history)
    most_recent_year = history[-1][0]
    most_recent_em = history[-1][1]

    # Anchor to the claim's stated baseline year when available and present in data.
    if baseline_year and baseline_year in history_dict:
        oldest_em = history_dict[baseline_year]
    else:
        oldest_em = history[0][1]

    newest_em = most_recent_em

    # For future targets, assess whether the recent trajectory is consistent with
    # reaching the target. Use slope of last ≤5 years to avoid early-year noise.
    if target_year and target_year > most_recent_year and is_reduction_claim:
        slope_window = history[-5:] if len(history) >= 5 else history
        if len(slope_window) >= 2:
            years_span = slope_window[-1][0] - slope_window[0][0]
            em_change = slope_window[-1][1] - slope_window[0][1]
            annual_slope = em_change / years_span if years_span > 0 else 0.0
            years_to_target = target_year - most_recent_year
            projected_em = most_recent_em + annual_slope * years_to_target
            # Net zero / carbon neutral claims: check if trajectory reaches ≤0
            if any(kw in claim_lower for kw in ("net zero", "carbon neutral", "zero emission")):
                if projected_em <= most_recent_em * 0.1:
                    return True, 0.6  # trajectory plausibly reaches near-zero
                if projected_em > most_recent_em * 0.5:
                    return False, 0.6  # trajectory clearly not approaching zero
                return None, 0.5  # ambiguous — insufficient slope signal
        # Fall through to absolute comparison if slope window too small.

    trend_up = newest_em > oldest_em * 1.05  # >5% increase = meaningful up
    trend_down = newest_em < oldest_em * 0.95  # >5% decrease = meaningful down

    if is_reduction_claim:
        if trend_down:
            return True, 0.75
        if trend_up:
            return False, 0.75
        return None, 0.6

    return None, 0.5

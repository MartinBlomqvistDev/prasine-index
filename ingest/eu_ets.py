"""EU ETS ingest module for the Prasine Index Verification Agent.

Queries the European Union Transaction Log (EUTL) for verified annual emissions
data for a company's registered installation IDs. EU ETS data is the
highest-quality evidence source in the pipeline: it is verified by accredited
independent third parties, mandated by EU Regulation 601/2012, and published
annually. A company claiming emissions reductions that are not reflected in EUTL
data is the most straightforward form of greenwashing.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from core.logger import get_logger
from core.retry import DataSourceError, RetryConfig, retry_async
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eu_ets_data"]

logger = get_logger(__name__)

_EU_ETS_BASE_URL: str = os.environ.get(
    "EU_ETS_BASE_URL",
    "https://ec.europa.eu/clima/ets",
)

# EUTL API endpoint for installation-level verified emissions.
# Returns annual verified emissions in tonnes CO2-equivalent per installation.
_EUTL_VERIFIED_EMISSIONS_PATH = "/api/installations/{installation_id}/verified-emissions"

# EU ETS data is published annually with approximately a 3-month lag.
# We retrieve the 5 most recent years to provide a trend for the Judge Agent.
_YEARS_TO_RETRIEVE: int = 5


async def fetch_eu_ets_data(
    claim: Claim,
    installation_ids: list[str],
) -> list[Evidence]:
    """Fetch verified annual emissions from the EU ETS EUTL for a company.

    Queries the EUTL for each of the company's registered EU ETS installation
    IDs and returns an Evidence record per installation with the verified
    annual emissions trend. Installations are queried sequentially to avoid
    overloading the EUTL public API; the Verification Agent's LangGraph graph
    calls this function in parallel with other ingest modules.

    Args:
        claim: The claim under assessment. Provides trace_id and claim_id
            for constructing Evidence records.
        installation_ids: List of EU ETS installation identifiers for the
            company. Retrieved from the Company.eu_ets_installation_ids field.

    Returns:
        List of :py:class:`~models.evidence.Evidence` records, one per
        installation for which data was successfully retrieved.

    Raises:
        :py:class:`~core.retry.DataSourceError`: If all installation queries
            fail. If some succeed, the successful records are returned and
            failures are logged as warnings.
    """
    async with httpx.AsyncClient(
        base_url=_EU_ETS_BASE_URL,
        timeout=httpx.Timeout(30.0),
        headers={"Accept": "application/json"},
    ) as client:
        evidence_records: list[Evidence] = []
        failures: list[str] = []

        for installation_id in installation_ids:
            try:
                record = await _fetch_installation(
                    client=client,
                    claim=claim,
                    installation_id=installation_id,
                )
                if record is not None:
                    evidence_records.append(record)
            except DataSourceError as exc:
                logger.warning(
                    f"EU ETS fetch failed for installation {installation_id}: {exc.message}",
                    extra={
                        "operation": "eu_ets_installation_failed",
                        "error_type": type(exc).__name__,
                        "http_status": exc.status_code,
                    },
                )
                failures.append(installation_id)

        if not evidence_records and failures:
            raise DataSourceError(
                message=(
                    f"All {len(failures)} EU ETS installation queries failed: "
                    f"{', '.join(failures)}"
                ),
                source=EvidenceSource.EU_ETS.value,
                retryable=True,
            )

        if failures:
            logger.warning(
                f"{len(failures)} EU ETS installation(s) failed; "
                f"{len(evidence_records)} succeeded.",
                extra={"operation": "eu_ets_partial"},
            )

        return evidence_records


@retry_async(config=RetryConfig.DEFAULT_HTTP, operation="eu_ets_installation_fetch")
async def _fetch_installation(
    client: httpx.AsyncClient,
    claim: Claim,
    installation_id: str,
) -> Evidence | None:
    """Fetch verified emissions for a single EU ETS installation.

    Args:
        client: Configured async httpx client with the EUTL base URL.
        claim: The claim under assessment.
        installation_id: The EU ETS installation identifier.

    Returns:
        An :py:class:`~models.evidence.Evidence` record, or None if the
        installation exists but has no data for the target period.

    Raises:
        :py:class:`~core.retry.DataSourceError`: On HTTP errors.
    """
    url = _EUTL_VERIFIED_EMISSIONS_PATH.format(installation_id=installation_id)

    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        from core.retry import classify_http_error
        raise classify_http_error(
            exc,
            source=EvidenceSource.EU_ETS.value,
        ) from exc

    data: dict[str, Any] = response.json()
    yearly_emissions: list[dict[str, Any]] = data.get("verifiedEmissions", [])

    if not yearly_emissions:
        logger.info(
            f"EU ETS: no verified emissions data for installation {installation_id}",
            extra={"operation": "eu_ets_no_data"},
        )
        return None

    # Take the most recent year as the primary data point
    latest = max(yearly_emissions, key=lambda r: r.get("year", 0))
    most_recent_year: int = latest.get("year", 0)
    most_recent_emissions: float = latest.get("verifiedEmissions", 0.0)

    # Build a trend summary from all available years for the Judge Agent
    trend_lines = [
        f"{r['year']}: {r['verifiedEmissions']:,.0f} tCO2e"
        for r in sorted(yearly_emissions, key=lambda r: r.get("year", 0))
        if r.get("verifiedEmissions") is not None
    ]
    trend_summary = " | ".join(trend_lines[-_YEARS_TO_RETRIEVE:])

    # Assess whether the data supports the claim.
    # EU ETS verified emissions increasing while the company claims reductions
    # is a contradiction. We use a simple heuristic here; the Judge Agent
    # performs the nuanced interpretation.
    supports_claim, confidence = _assess_emissions_vs_claim(
        claim_text=claim.raw_text,
        yearly_emissions=yearly_emissions,
    )

    summary = (
        f"EU ETS EUTL verified emissions for installation {installation_id}: "
        f"{most_recent_emissions:,.0f} tCO2e in {most_recent_year}. "
        f"Trend ({_YEARS_TO_RETRIEVE} years): {trend_summary}."
    )

    return Evidence(
        claim_id=claim.id,
        trace_id=claim.trace_id,
        source=EvidenceSource.EU_ETS,
        evidence_type=EvidenceType.VERIFIED_EMISSIONS,
        source_url=f"{_EU_ETS_BASE_URL}{url}",
        raw_data={
            "installation_id": installation_id,
            "verified_emissions": yearly_emissions,
            "installation_name": data.get("installationName"),
            "permit_id": data.get("permitId"),
        },
        summary=summary,
        data_year=most_recent_year if most_recent_year else None,
        supports_claim=supports_claim,
        confidence=confidence,
    )


def _assess_emissions_vs_claim(
    claim_text: str,
    yearly_emissions: list[dict[str, Any]],
) -> tuple[bool | None, float]:
    """Heuristically assess whether EU ETS data supports the claim.

    This is a lightweight signal for the Evidence record. The Judge Agent
    performs the authoritative interpretation. A heuristic that detects
    obvious contradictions (rising emissions against reduction claims) is
    better than returning None for every record.

    Args:
        claim_text: The verbatim claim text.
        yearly_emissions: List of annual verified emissions dicts.

    Returns:
        A tuple of (supports_claim, confidence). Confidence is reduced when
        the heuristic cannot be applied (e.g. claim is about future targets).
    """
    claim_lower = claim_text.lower()

    reduction_keywords = (
        "reduc", "decreas", "lower", "cut", "decarboni", "net zero", "carbon neutral",
    )

    is_reduction_claim = any(kw in claim_lower for kw in reduction_keywords)

    if len(yearly_emissions) < 2:
        # Insufficient data to determine trend
        return None, 0.5

    sorted_by_year = sorted(yearly_emissions, key=lambda r: r.get("year", 0))
    recent = [r["verifiedEmissions"] for r in sorted_by_year[-3:] if r.get("verifiedEmissions")]

    if len(recent) < 2:
        return None, 0.5

    trend_up = recent[-1] > recent[0]
    trend_down = recent[-1] < recent[0]

    if is_reduction_claim:
        if trend_down:
            return True, 0.75
        if trend_up:
            return False, 0.75
        return None, 0.6

    # For non-reduction claims, EU ETS data is contextual rather than directly
    # supporting or contradicting
    return None, 0.5

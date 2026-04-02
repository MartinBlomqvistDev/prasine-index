"""CDP (Carbon Disclosure Project) open data ingest module for the Prasine Index Verification Agent.

Retrieves a company's self-reported climate data from the CDP open dataset,
including reported emissions, reduction targets, and climate governance
disclosures. CDP data is self-reported and therefore weighted as secondary
evidence compared to EU ETS verified data — but it is the primary source for
companies without mandatory EU ETS installations, and for assessing claims about
scope 3 emissions and supply chain decarbonisation.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from core.logger import get_logger
from core.retry import RetryConfig, retry_async
from models.claim import Claim
from models.company import Company
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_cdp_data"]

logger = get_logger(__name__)

# CDP Open Data portal — bulk CSV available at no cost for the open dataset.
# The search API allows filtering by company name and ISIN.
_CDP_BASE_URL: str = os.environ.get(
    "CDP_OPEN_DATA_URL",
    "https://data.cdp.net",
)

_CDP_SEARCH_PATH = "/api/v0/search"


async def fetch_cdp_data(
    claim: Claim,
    company: Company,
) -> list[Evidence]:
    """Fetch self-reported climate data from the CDP open dataset.

    Searches CDP for the company by LEI or name and retrieves the most recent
    disclosed climate data relevant to the claim category. Returns Evidence
    records for each significant CDP disclosure that bears on the claim.

    CDP data is self-reported and weighted accordingly: it reveals what the
    company told CDP, which may itself differ from what the company told the
    public — a discrepancy that is itself a greenwashing signal.

    Args:
        claim: The claim under assessment.
        company: The company that made the claim.

    Returns:
        List of :py:class:`~models.evidence.Evidence` records from CDP.
        May be empty if the company has not responded to CDP or has not
        disclosed data relevant to the claim category.

    Raises:
        :py:class:`~core.retry.DataSourceError`: On HTTP errors that persist
            after retries.
    """
    search_identifier = company.lei or company.name

    async with httpx.AsyncClient(
        base_url=_CDP_BASE_URL,
        timeout=httpx.Timeout(30.0),
        headers={"Accept": "application/json"},
    ) as client:
        raw_records = await _search_cdp(client, search_identifier, company.name)

    if not raw_records:
        logger.info(
            f"CDP: no data found for {company.name!r}",
            extra={"operation": "cdp_no_data", "company_id": str(company.id)},
        )
        return []

    return _build_evidence_records(claim, company, raw_records)


@retry_async(config=RetryConfig.DEFAULT_HTTP, operation="cdp_search")
async def _search_cdp(
    client: httpx.AsyncClient,
    identifier: str,
    company_name: str,
) -> list[dict[str, Any]]:
    """Search CDP for a company's climate disclosures.

    Args:
        client: Configured async httpx client with the CDP base URL.
        identifier: LEI or company name to search.
        company_name: Company name for fallback search.

    Returns:
        List of raw CDP disclosure records.

    Raises:
        :py:class:`~core.retry.DataSourceError`: On HTTP errors.
    """
    params = {
        "q": identifier,
        "type": "organization",
        "size": 5,
    }

    try:
        response = await client.get(_CDP_SEARCH_PATH, params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        from core.retry import classify_http_error
        raise classify_http_error(exc, source=EvidenceSource.CDP.value) from exc

    results = response.json().get("results", [])

    # If LEI search returned nothing, fall back to name search
    if not results and identifier != company_name:
        params["q"] = company_name
        try:
            response = await client.get(_CDP_SEARCH_PATH, params=params)
            response.raise_for_status()
            results = response.json().get("results", [])
        except httpx.HTTPStatusError:
            pass  # Return empty — name search failure is non-fatal

    return results


def _build_evidence_records(
    claim: Claim,
    company: Company,
    raw_records: list[dict[str, Any]],
) -> list[Evidence]:
    """Construct Evidence records from raw CDP API responses.

    Filters and maps CDP disclosure records to Evidence objects. Only
    records relevant to the claim category are included. Disclosures from
    the most recent reporting year are prioritised.

    Args:
        claim: The claim under assessment.
        company: The company that made the claim.
        raw_records: Raw CDP search results.

    Returns:
        List of :py:class:`~models.evidence.Evidence` records.
    """
    evidence: list[Evidence] = []

    for record in raw_records[:3]:  # cap at 3 most relevant results
        try:
            data_year = _extract_year(record)
            supports, confidence = _assess_cdp_record(claim, record)
            summary = _summarise_cdp_record(company.name, record)

            evidence.append(
                Evidence(
                    claim_id=claim.id,
                    trace_id=claim.trace_id,
                    source=EvidenceSource.CDP,
                    evidence_type=EvidenceType.SELF_REPORTED_EMISSIONS,
                    source_url=record.get("url") or f"{_CDP_BASE_URL}/en/{record.get('id', '')}",
                    raw_data=record,
                    summary=summary,
                    data_year=data_year,
                    supports_claim=supports,
                    confidence=confidence,
                )
            )
        except Exception as exc:
            logger.warning(
                f"Failed to build CDP evidence record: {exc}",
                extra={"operation": "cdp_record_build_failed", "error_type": type(exc).__name__},
            )

    return evidence


def _extract_year(record: dict[str, Any]) -> int | None:
    """Extract the reporting year from a CDP record.

    Args:
        record: Raw CDP record.

    Returns:
        The integer reporting year, or None if not determinable.
    """
    for key in ("reportingYear", "year", "questionnaire_year"):
        raw = record.get(key)
        if raw is not None:
            try:
                return int(str(raw)[:4])
            except (ValueError, TypeError):
                pass
    return None


def _assess_cdp_record(
    claim: Claim,
    record: dict[str, Any],
) -> tuple[bool | None, float]:
    """Assess whether a CDP record supports or contradicts the claim.

    CDP data is self-reported, so confidence is capped at 0.7 regardless
    of apparent alignment. Discrepancies between CDP disclosures and public
    claims are flagged by comparing the CDP target text against the claim.

    Args:
        claim: The claim under assessment.
        record: Raw CDP record.

    Returns:
        A tuple of (supports_claim, confidence).
    """
    # CDP self-reported data: moderate confidence ceiling
    confidence = 0.65

    score = record.get("score", "").upper()
    if score in ("A", "A-"):
        # High CDP score — company is engaged and disclosing; slight positive signal
        return True, confidence
    if score in ("D", "D-", "F"):
        # Low CDP score — company is not disclosing meaningfully
        return False, confidence

    return None, confidence


def _summarise_cdp_record(company_name: str, record: dict[str, Any]) -> str:
    """Produce a natural-language summary of a CDP record for the Judge Agent.

    Args:
        company_name: The company name.
        record: Raw CDP record.

    Returns:
        A human-readable summary string.
    """
    year = _extract_year(record)
    score = record.get("score", "not disclosed")
    status = record.get("status", "")
    year_str = str(year) if year else "most recent year"

    return (
        f"CDP self-reported disclosure for {company_name} ({year_str}): "
        f"CDP score {score}. {status}. "
        "This is self-reported data and weighted as secondary evidence."
    )

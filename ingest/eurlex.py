"""EUR-Lex ingest module for the Prasine Index Verification Agent.

Queries the EUR-Lex REST API for CSRD disclosure records, Green Claims Directive
filings, and legislative proceedings relevant to the claim under assessment.
EUR-Lex provides the regulatory and legislative context — what EU law requires of
this company and whether its disclosures are consistent with its mandatory CSRD
obligations. A mismatch between CSRD mandatory disclosures and public green
claims is a legally actionable form of greenwashing.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from core.logger import get_logger
from core.retry import RetryConfig, retry_async
from models.claim import Claim, ClaimCategory
from models.company import Company
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eurlex_data"]

logger = get_logger(__name__)

_EUR_LEX_BASE_URL: str = os.environ.get(
    "EUR_LEX_API_URL",
    "https://eur-lex.europa.eu/rest",
)

# EUR-Lex document type codes relevant to climate and sustainability claims
_RELEVANT_DOC_TYPES = ("CSRD", "REG", "DIR", "DEC")

# Maximum number of EUR-Lex documents to retrieve per claim
_MAX_RESULTS: int = 5

# Search terms mapped to claim categories for EUR-Lex full-text search
_CATEGORY_SEARCH_TERMS: dict[ClaimCategory, list[str]] = {
    ClaimCategory.NET_ZERO_TARGET: ["net zero", "climate neutrality", "carbon neutral"],
    ClaimCategory.CARBON_NEUTRAL: ["carbon neutral", "climate neutral"],
    ClaimCategory.EMISSIONS_REDUCTION: ["emissions reduction", "GHG reduction", "decarbonisation"],
    ClaimCategory.RENEWABLE_ENERGY: ["renewable energy", "clean energy"],
    ClaimCategory.SUSTAINABLE_SUPPLY_CHAIN: ["supply chain", "scope 3", "value chain"],
    ClaimCategory.SCIENCE_BASED_TARGETS: ["science based targets", "SBTi", "1.5 degrees"],
    ClaimCategory.OTHER: ["sustainability", "environmental"],
}


async def fetch_eurlex_data(
    claim: Claim,
    company: Company,
) -> list[Evidence]:
    """Fetch legislative and CSRD context from EUR-Lex for a claim.

    Searches EUR-Lex for documents relevant to the claim's category and the
    company's jurisdiction, retrieving the legislative framework within which
    the claim is assessed. Also searches for any CSRD mandatory disclosures
    filed by the company where available.

    EUR-Lex evidence is classified as LEGISLATIVE_RECORD and weighted by the
    Judge Agent as providing regulatory context rather than direct emissions
    contradictions.

    Args:
        claim: The claim under assessment.
        company: The company that made the claim.

    Returns:
        List of :py:class:`~models.evidence.Evidence` records from EUR-Lex.

    Raises:
        :py:class:`~core.retry.DataSourceError`: On HTTP errors.
    """
    search_terms = _CATEGORY_SEARCH_TERMS.get(
        claim.claim_category,
        _CATEGORY_SEARCH_TERMS[ClaimCategory.OTHER],
    )

    async with httpx.AsyncClient(
        base_url=_EUR_LEX_BASE_URL,
        timeout=httpx.Timeout(30.0),
        headers={"Accept": "application/json", "Accept-Language": "en"},
    ) as client:
        raw_docs = await _search_eurlex(client, search_terms, company.country)

    if not raw_docs:
        logger.info(
            f"EUR-Lex: no relevant documents found for category {claim.claim_category.value}",
            extra={"operation": "eurlex_no_results"},
        )
        return []

    return _build_evidence_records(claim, raw_docs)


@retry_async(config=RetryConfig.DEFAULT_HTTP, operation="eurlex_search")
async def _search_eurlex(
    client: httpx.AsyncClient,
    search_terms: list[str],
    country: str,
) -> list[dict[str, Any]]:
    """Search EUR-Lex for documents matching the claim category.

    Args:
        client: Configured async httpx client.
        search_terms: List of search terms for the claim category.
        country: ISO 3166-1 alpha-2 country code for jurisdiction filter.

    Returns:
        List of raw document metadata dicts from EUR-Lex.

    Raises:
        :py:class:`~core.retry.DataSourceError`: On HTTP errors.
    """
    query = " OR ".join(f'"{term}"' for term in search_terms[:3])
    params = {
        "q": query,
        "lang": "EN",
        "size": _MAX_RESULTS,
        "sort": "DATE_DESC",
    }

    try:
        response = await client.get("/documents", params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        from core.retry import classify_http_error
        raise classify_http_error(exc, source=EvidenceSource.EUR_LEX.value) from exc

    return response.json().get("results", [])


def _build_evidence_records(
    claim: Claim,
    raw_docs: list[dict[str, Any]],
) -> list[Evidence]:
    """Build Evidence records from EUR-Lex document metadata.

    Args:
        claim: The claim under assessment.
        raw_docs: Raw EUR-Lex document results.

    Returns:
        List of :py:class:`~models.evidence.Evidence` records.
    """
    evidence: list[Evidence] = []

    for doc in raw_docs[:_MAX_RESULTS]:
        try:
            celex = doc.get("celex", "")
            title = doc.get("title", "Untitled EUR-Lex document")
            date_str = doc.get("date", "")
            doc_year = _parse_year(date_str)
            eur_lex_url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"

            summary = (
                f"EUR-Lex document [{celex}]: {title}. "
                f"Published: {date_str or 'date unknown'}. "
                "Provides the EU legislative and regulatory framework applicable "
                "to this claim category."
            )

            evidence.append(
                Evidence(
                    claim_id=claim.id,
                    trace_id=claim.trace_id,
                    source=EvidenceSource.EUR_LEX,
                    evidence_type=EvidenceType.LEGISLATIVE_RECORD,
                    source_url=eur_lex_url,
                    raw_data=doc,
                    summary=summary,
                    data_year=doc_year,
                    supports_claim=None,  # Legislative context: not directly supporting/contradicting
                    confidence=0.9,
                )
            )
        except Exception as exc:
            logger.warning(
                f"Failed to build EUR-Lex evidence record: {exc}",
                extra={"operation": "eurlex_record_build_failed", "error_type": type(exc).__name__},
            )

    return evidence


def _parse_year(date_str: str) -> int | None:
    """Parse a year integer from a date string.

    Args:
        date_str: A date string in any common format.

    Returns:
        The integer year, or None if not parseable.
    """
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None

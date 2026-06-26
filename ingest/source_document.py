"""Source document ingest: fetch and analyse the claim's own source document.

When a claim references a company document (sustainability report, annual
report, IR page), this module fetches that document and uses Claude Haiku
with forced tool use to extract structured climate disclosures — scope 1/2/3
emissions, net-zero baseline year, interim targets, and certified carbon
removal plan.

This is the most direct verification step: comparing the claim against the
document it explicitly cites. A company that says "see our sustainability
report for our net-zero goals" but whose report lacks EmpCo-required elements
is in substantiation failure under binding EU law, regardless of what external
sources show.

Handles both HTML pages (tag-stripped) and PDF documents (passed as base64
document blocks to the Anthropic API).
"""

from __future__ import annotations

import base64
import io
import re
from typing import Any

import anthropic
import httpx

from core.logger import get_logger
from core.retry import DataSourceError
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_source_document_data"]

logger = get_logger(__name__)

_TOOL_NAME = "extract_climate_disclosures"
_MAX_HTML_CHARS = 80_000
_MAX_PDF_PAGES = 100  # Anthropic document API hard limit
_FETCH_TIMEOUT = 45.0

_EXTRACTION_TOOL: anthropic.types.ToolParam = {
    "name": _TOOL_NAME,
    "description": (
        "Extract structured climate and net-zero disclosures from a company's "
        "source document. Focus on what the document actually discloses versus "
        "what is absent or missing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "scope1_mt": {
                "type": "number",
                "description": (
                    "Scope 1 absolute GHG emissions in million tonnes CO2e, latest year. "
                    "Omit if not disclosed."
                ),
            },
            "scope2_mt": {
                "type": "number",
                "description": "Scope 2 absolute GHG emissions in million tonnes CO2e. Omit if not disclosed.",
            },
            "scope3_mt": {
                "type": "number",
                "description": "Scope 3 absolute GHG emissions in million tonnes CO2e. Omit if not disclosed.",
            },
            "emissions_year": {
                "type": "integer",
                "description": "Reporting year for the emissions figures.",
            },
            "baseline_year": {
                "type": "integer",
                "description": "Baseline year for the net-zero or reduction target. Omit if not disclosed.",
            },
            "interim_target_2030": {
                "type": "string",
                "description": "Description of the 2030 interim reduction target. Omit if absent.",
            },
            "interim_target_2035": {
                "type": "string",
                "description": "Description of the 2035 interim target. Omit if absent.",
            },
            "interim_target_2040": {
                "type": "string",
                "description": "Description of the 2040 interim target. Omit if absent.",
            },
            "has_certified_removal_plan": {
                "type": "boolean",
                "description": (
                    "True only if the document explicitly describes certified permanent "
                    "carbon removal mechanisms (DAC, BECCS, biochar, etc.) — NOT carbon "
                    "offsets or offset credits. False if only offsets are mentioned or "
                    "removals are not addressed."
                ),
            },
            "removal_mechanism_description": {
                "type": "string",
                "description": "Description of the certified removal mechanism if present.",
            },
            "saf_current_pct": {
                "type": "number",
                "description": "Current SAF blend percentage actually in use. Aviation sector only.",
            },
            "saf_target_pct": {
                "type": "number",
                "description": "SAF blend target percentage. Aviation sector only.",
            },
            "saf_target_year": {
                "type": "integer",
                "description": "Year by which the SAF target is to be achieved.",
            },
            "empco_gaps": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "EmpCo Directive (EU 2024/825) substantiation elements MISSING from "
                    "the document. Include only elements that are genuinely absent. "
                    "Valid values: 'baseline_year', 'interim_2030', 'interim_2035', "
                    "'interim_2040', 'abatement_removal_split', "
                    "'certified_removal_plan', 'verified_transition_plan'."
                ),
            },
            "supports_claim": {
                "type": "boolean",
                "description": (
                    "False if the document fails to substantiate the claim — i.e. the "
                    "claim implies verified net-zero credentials but the document lacks "
                    "required EmpCo elements, or disclosed emissions data is inconsistent "
                    "with the claimed trajectory. True only if the document provides "
                    "genuine, complete substantiation."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Confidence in the supports_claim assessment (0–1).",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Concise factual summary citing actual figures and missing elements. "
                    "Be specific: name the emissions figures, the gaps, and the SAF numbers."
                ),
            },
        },
        "required": [
            "has_certified_removal_plan",
            "empco_gaps",
            "supports_claim",
            "confidence",
            "summary",
        ],
    },
}

_SYSTEM_PROMPT = """\
You are a specialist in EU corporate climate disclosure analysis. \
Read the company's source document and extract structured factual data \
about what it actually discloses regarding climate and net-zero commitments.

Be strictly factual — extract only what the document explicitly states. \
Do not infer or assume information that is not present.

Under the EmpCo Directive (EU 2024/825), a net-zero claim requires: \
a disclosed baseline year, interim reduction checkpoints at 2030/2035/2040, \
a split between emissions abatement and certified permanent carbon removals, \
and a verified transition plan that does NOT rely solely on offset credits. \
Carbon offsetting is NOT the same as certified carbon removal. \
A document that relies on offsets for net-zero has NOT met the removal requirement.\
"""


async def fetch_source_document_data(
    claim: Claim,
    client: anthropic.AsyncAnthropic,
) -> list[Evidence]:
    """Fetch and analyse the claim's source document for climate disclosures.

    Retrieves claim.source_url, detects HTML vs PDF, passes content to Claude
    Haiku via forced tool use, and returns a structured Evidence record
    assessing whether the document substantiates the claim.

    Args:
        claim: The claim under assessment. Must have a non-empty source_url.
        client: Shared Anthropic async client.

    Returns:
        A list with one Evidence record, or empty list if source_url is absent
        or the document cannot be fetched.

    Raises:
        DataSourceError: On HTTP failure (caught by the calling node).
    """
    if not claim.source_url:
        return []

    logger.info(
        f"Fetching source document: {claim.source_url}",
        extra={"operation": "source_doc_fetch_start", "url": claim.source_url},
    )

    try:
        content_type, content_bytes = await _fetch_content(claim.source_url)
    except DataSourceError:
        raise
    except Exception as exc:
        raise DataSourceError(
            message=f"Failed to fetch {claim.source_url}: {exc}",
            source="SOURCE_DOCUMENT",
        ) from exc

    content_blocks: list[dict[str, Any]] = []

    is_pdf = "pdf" in content_type.lower() or claim.source_url.lower().endswith(".pdf")
    if is_pdf:
        page_count = _pdf_page_count(content_bytes)
        if page_count <= _MAX_PDF_PAGES:
            b64 = base64.standard_b64encode(content_bytes).decode()
            content_blocks.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64,
                    },
                }
            )
            logger.info(
                f"Source document is PDF ({len(content_bytes) // 1024} KB, {page_count} pages)",
                extra={"operation": "source_doc_pdf", "size_kb": len(content_bytes) // 1024},
            )
        else:
            text = _extract_pdf_text(content_bytes)[:_MAX_HTML_CHARS]
            content_blocks.append({"type": "text", "text": text})
            logger.info(
                f"PDF has {page_count} pages (>{_MAX_PDF_PAGES} limit) — falling back to text extraction "
                f"({len(text)} chars)",
                extra={"operation": "source_doc_pdf_text_fallback", "page_count": page_count},
            )
    else:
        text = _strip_html(content_bytes.decode("utf-8", errors="replace"))[:_MAX_HTML_CHARS]
        content_blocks.append({"type": "text", "text": text})
        logger.info(
            f"Source document is HTML ({len(text)} chars after stripping)",
            extra={"operation": "source_doc_html", "chars": len(text)},
        )

    content_blocks.append(
        {
            "type": "text",
            "text": (
                f'\nCLAIM UNDER ASSESSMENT:\n"{claim.raw_text}"\n\n'
                "Extract all climate and net-zero disclosures from this document "
                "as they relate to the claim above."
            ),
        }
    )

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            tools=[_EXTRACTION_TOOL],
            tool_choice=anthropic.types.ToolChoiceToolParam(type="tool", name=_TOOL_NAME),
            messages=[{"role": "user", "content": content_blocks}],  # type: ignore[typeddict-item]
        )
    except anthropic.APIStatusError as exc:
        raise DataSourceError(
            message=f"Anthropic API error analysing source document: {exc.status_code}",
            source="SOURCE_DOCUMENT",
            status_code=exc.status_code,
        ) from exc

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        logger.warning(
            "Source document analysis returned no tool block",
            extra={"operation": "source_doc_no_tool_block"},
        )
        return []

    extraction: dict[str, Any] = tool_block.input
    supports_claim: bool | None = extraction.get("supports_claim")
    confidence: float = float(extraction.get("confidence", 0.70))
    summary: str = extraction.get("summary", "Source document analysis completed.")
    empco_gaps: list[str] = extraction.get("empco_gaps", [])

    raw_data: dict[str, Any] = {
        "source_url": claim.source_url,
        "content_type": content_type,
        "scope1_mt": extraction.get("scope1_mt"),
        "scope2_mt": extraction.get("scope2_mt"),
        "scope3_mt": extraction.get("scope3_mt"),
        "emissions_year": extraction.get("emissions_year"),
        "baseline_year": extraction.get("baseline_year"),
        "interim_target_2030": extraction.get("interim_target_2030"),
        "interim_target_2035": extraction.get("interim_target_2035"),
        "interim_target_2040": extraction.get("interim_target_2040"),
        "has_certified_removal_plan": extraction.get("has_certified_removal_plan"),
        "removal_mechanism_description": extraction.get("removal_mechanism_description"),
        "saf_current_pct": extraction.get("saf_current_pct"),
        "saf_target_pct": extraction.get("saf_target_pct"),
        "saf_target_year": extraction.get("saf_target_year"),
        "empco_gaps": empco_gaps,
    }

    logger.info(
        f"Source document analysis complete: supports_claim={supports_claim}, "
        f"confidence={confidence:.2f}, empco_gaps={empco_gaps}",
        extra={
            "operation": "source_doc_complete",
            "supports_claim": supports_claim,
            "confidence": confidence,
            "empco_gap_count": len(empco_gaps),
        },
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.SOURCE_DOCUMENT,
            evidence_type=EvidenceType.SELF_REPORTED_DISCLOSURE,
            source_url=claim.source_url,
            raw_data=raw_data,
            summary=summary,
            data_year=extraction.get("emissions_year")
            if isinstance(extraction.get("emissions_year"), int)
            else None,
            supports_claim=supports_claim,
            confidence=confidence,
        )
    ]


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF, or 0 if unreadable."""
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        return 0


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract plain text from a PDF using pypdf."""
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return re.sub(r"\s+", " ", " ".join(parts)).strip()
    except Exception as exc:
        return f"[PDF text extraction failed: {exc}]"


async def _fetch_content(url: str) -> tuple[str, bytes]:
    """Fetch a URL and return (content_type, raw_bytes).

    Args:
        url: The URL to fetch.

    Returns:
        Tuple of (content_type, response_body_bytes).

    Raises:
        DataSourceError: On HTTP 4xx/5xx.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; PrasineIndex/1.0; +https://prasineindex.com)",
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
    }
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as http:
        response = await http.get(url)

    if response.status_code >= 400:
        raise DataSourceError(
            message=f"HTTP {response.status_code} fetching {url}",
            source="SOURCE_DOCUMENT",
            status_code=response.status_code,
        )

    content_type = response.headers.get("content-type", "text/html")
    return content_type, response.content


def _strip_html(html: str) -> str:
    """Remove HTML tags and normalise whitespace.

    Args:
        html: Raw HTML string.

    Returns:
        Plain text with tags removed and whitespace normalised.
    """
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(r"<[^>]+>", " ", html)
    for entity, char in (
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&nbsp;", " "),
        ("&#39;", "'"),
        ("&quot;", '"'),
    ):
        html = html.replace(entity, char)
    return re.sub(r"\s+", " ", html).strip()

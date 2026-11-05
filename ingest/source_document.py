"""Source document ingest: fetch and analyse the claim's own source document.

When a claim references a company document (sustainability report, annual
report, IR page), this module fetches that document and uses Claude Haiku
with tool use to extract structured climate disclosures: scope 1/2/3
emissions, the target baseline year, interim targets, the use of offset credits
and removals, and which elements of an implementation plan the document shows.

This is the most direct verification step: comparing the claim against the
document it explicitly cites. For a claim about future performance, the
checklist is the list of elements in Article 6(2)(d) of the Unfair Commercial
Practices Directive as amended by Directive (EU) 2024/825. The module records
which elements the document shows; it does not decide whether the law is
breached.

Handles both HTML pages (tag-stripped) and PDF documents (passed as base64
document blocks to the Anthropic API).
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Any
from urllib.parse import urljoin

import anthropic
import httpx

from core.logger import get_logger
from core.model_requests import TOOL_CALL_ATTEMPTS
from core.retry import DataSourceError
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_source_document_data"]

logger = get_logger(__name__)

_TOOL_NAME = "extract_climate_disclosures"
_MODEL_ID = "claude-haiku-5-5"
_MAX_HTML_CHARS = 80_000
_MAX_LINKED_CHARS = 60_000

# Words in a PDF link's address that mark the company report behind a claim
# page, with their weight. A link needs a weight of two to be read.
_REPORT_WORDS = (
    ("sustainab", 2),
    ("climate", 2),
    ("esg", 1),
    ("report", 1),
    ("statement", 1),
    ("annual", 1),
    ("integrated", 1),
    ("transition", 1),
    ("csrd", 1),
    ("tcfd", 1),
)

# Words that mark the pages of a long report that concern climate.
_PAGE_WORDS = (
    "net zero",
    "net-zero",
    "scope 1",
    "scope 2",
    "scope 3",
    "emission",
    "target",
    "transition plan",
    "carbon",
    "co2",
    "sustainable aviation fuel",
    "renewable",
)
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
            "interim_targets": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Each interim target the document states, as 'YEAR: target'. "
                    "Empty if the document states none."
                ),
            },
            "relies_on_offset_credits": {
                "type": "boolean",
                "description": (
                    "True if the document says the target or claim will be met partly "
                    "or wholly by buying offset credits for emissions outside the "
                    "company's own value chain."
                ),
            },
            "removals_described": {
                "type": "boolean",
                "description": (
                    "True if the document describes carbon removals (for example "
                    "direct air capture, BECCS or biochar) as distinct from offset credits."
                ),
            },
            "removal_mechanism_description": {
                "type": "string",
                "description": "What the document says about removals, if anything.",
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
            "missing_plan_elements": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "public_verifiable_commitments",
                        "detailed_implementation_plan",
                        "measurable_time_bound_targets",
                        "resource_allocation",
                        "independent_third_party_verification",
                        "verification_findings_published",
                    ],
                },
                "description": (
                    "Only for a claim about future environmental performance: the "
                    "elements listed in Article 6(2)(d) of the Unfair Commercial "
                    "Practices Directive, as amended, that this document does not show. "
                    "Include only elements that are genuinely absent from the document. "
                    "Leave empty for a claim about past or present performance."
                ),
            },
            "supports_claim": {
                "type": "boolean",
                "description": (
                    "False if the document does not back the claim as made: its figures "
                    "contradict the claim, or the claim is about future performance and "
                    "the document lacks the plan elements needed to support it. True "
                    "only if the document substantiates the claim as made."
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
                    "Concise factual summary citing the document's figures and the elements "
                    "it does not show, in plain words. Quote what the document says about "
                    "the company's fossil fuel strategy if it says anything. Never name or "
                    "cite a law or a legal provision."
                ),
            },
        },
        "required": [
            "missing_plan_elements",
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

Be strictly factual: extract only what the document explicitly states. \
Do not infer or assume information that is not present.

For a claim about future environmental performance, such as a net-zero target, \
check the document against the elements that Article 6(2)(d) of the Unfair \
Commercial Practices Directive, as amended by Directive (EU) 2024/825, lists: \
clear, objective, publicly available and verifiable commitments; a detailed and \
realistic implementation plan; measurable and time-bound targets; other elements \
needed to implement it, such as allocation of resources; regular verification by \
an independent third-party expert; and findings of that verification made \
available to consumers. Record which of these the document does not show. In the \
summary, describe them in plain words, such as "no implementation plan" or "no \
independent verification": never name or cite the provision or any other law, and \
never say whether a law is breached.

If the document says anything about the company's own fossil fuel strategy, such \
as coal, oil or gas production, a phase-down or an expansion, quote it in the \
summary: it is the company's stated position and belongs beside any record about \
its fossil fuel supply.

Offset credits bought for emissions outside the company's value chain are not \
the same as carbon removals. Record what the document says about each, as stated.\
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
    linked_url: str | None = None
    linked_read = False

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
        html = content_bytes.decode("utf-8", errors="replace")
        text = _strip_html(html)[:_MAX_HTML_CHARS]
        content_blocks.append({"type": "text", "text": text})
        logger.info(
            f"Source document is HTML ({len(text)} chars after stripping)",
            extra={"operation": "source_doc_html", "chars": len(text)},
        )
        linked_url = _linked_report(html, claim.source_url)
        if linked_url:
            linked_text = await _read_linked_report(linked_url)
            if linked_text:
                linked_read = True
                content_blocks.append(
                    {
                        "type": "text",
                        "text": (
                            f"\nLINKED DOCUMENT: the page links to {linked_url}. The pages "
                            "of it that concern climate follow, each marked with its page "
                            f"number.\n{linked_text}"
                        ),
                    }
                )

    content_blocks.append(
        {
            "type": "text",
            "text": (
                f'\nCLAIM UNDER ASSESSMENT:\n"{claim.raw_text}"\n\n'
                "Extract all climate and net-zero disclosures from this document "
                f"as they relate to the claim above. Call the {_TOOL_NAME} tool once "
                "with your findings."
                + (
                    " The page and the linked document are both the company's own. "
                    "In the summary, say which statements come from the page and "
                    "which from the linked document, with its page numbers."
                    if linked_read
                    else ""
                )
            ),
        }
    )

    # Current models reject a forced tool_choice, so the request asks for the
    # tool in the prompt and is sent again if the model answers without it.
    tool_block: anthropic.types.ToolUseBlock | None = None
    for _attempt in range(TOOL_CALL_ATTEMPTS):
        try:
            response = await client.messages.create(  # type: ignore[call-overload]
                model=_MODEL_ID,
                max_tokens=16000,
                system=_SYSTEM_PROMPT,
                tools=[_EXTRACTION_TOOL],
                output_config={"effort": "medium"},
                messages=[{"role": "user", "content": content_blocks}],
            )
        except anthropic.APIStatusError as exc:
            raise DataSourceError(
                message=f"Anthropic API error analysing source document: {exc.status_code}",
                source="SOURCE_DOCUMENT",
                status_code=exc.status_code,
            ) from exc

        if response.stop_reason == "refusal":
            raise DataSourceError(
                message="The model declined to analyse the source document.",
                source="SOURCE_DOCUMENT",
                retryable=False,
            )

        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is not None:
            break

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
    missing_plan_elements: list[str] = extraction.get("missing_plan_elements", [])
    if linked_url and not linked_read:
        summary = f"{summary} The page links to {linked_url}, which this assessment could not read."

    raw_data: dict[str, Any] = {
        "source_url": claim.source_url,
        "content_type": content_type,
        "scope1_mt": extraction.get("scope1_mt"),
        "scope2_mt": extraction.get("scope2_mt"),
        "scope3_mt": extraction.get("scope3_mt"),
        "emissions_year": extraction.get("emissions_year"),
        "baseline_year": extraction.get("baseline_year"),
        "interim_targets": extraction.get("interim_targets", []),
        "relies_on_offset_credits": extraction.get("relies_on_offset_credits"),
        "removals_described": extraction.get("removals_described"),
        "removal_mechanism_description": extraction.get("removal_mechanism_description"),
        "saf_current_pct": extraction.get("saf_current_pct"),
        "saf_target_pct": extraction.get("saf_target_pct"),
        "saf_target_year": extraction.get("saf_target_year"),
        "missing_plan_elements": missing_plan_elements,
        "linked_document": linked_url,
        "linked_document_read": linked_read,
    }

    logger.info(
        f"Source document analysis complete: supports_claim={supports_claim}, "
        f"confidence={confidence:.2f}, missing_plan_elements={missing_plan_elements}",
        extra={
            "operation": "source_doc_complete",
            "supports_claim": supports_claim,
            "confidence": confidence,
            "missing_plan_element_count": len(missing_plan_elements),
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


def _linked_report(html: str, page_url: str) -> str | None:
    """Return the address of the company report a claim page links to, if any.

    A climate page often states a claim in a sentence and links to the report
    that sets it out. The PDF link whose address weighs most as a
    sustainability, climate or annual report is read with the page.

    Args:
        html: The page's HTML.
        page_url: The page's address, for resolving relative links.

    Returns:
        The absolute address of the report, or None.
    """
    best: tuple[int, str] | None = None
    for href in re.findall(r"href=[\"']([^\"']+?\.pdf[^\"']*)[\"']", html, flags=re.IGNORECASE):
        url = urljoin(page_url, href.replace("&amp;", "&"))
        weight = sum(w for word, w in _REPORT_WORDS if word in url.lower())
        if weight >= 2 and (best is None or weight > best[0]):
            best = (weight, url)
    return best[1] if best else None


def _climate_pages(pdf_bytes: bytes, limit: int = _MAX_LINKED_CHARS) -> str:
    """Return the pages of a PDF that concern climate most, in page order.

    Args:
        pdf_bytes: The PDF.
        limit: The most characters to return.

    Returns:
        The chosen pages, each marked with its page number, or "" when the PDF
        cannot be read or no page concerns climate.
    """
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = [re.sub(r"\s+", " ", page.extract_text() or "").strip() for page in reader.pages]
    except Exception:
        return ""
    weights = [sum(text.lower().count(word) for word in _PAGE_WORDS) for text in pages]
    chosen: list[int] = []
    total = 0
    for index in sorted(range(len(pages)), key=lambda i: -weights[i]):
        if weights[index] == 0:
            break
        if total + len(pages[index]) > limit:
            continue
        chosen.append(index)
        total += len(pages[index])
    return "\n".join(f"[page {i + 1}] {pages[i]}" for i in sorted(chosen))


async def _read_linked_report(url: str) -> str:
    """Fetch a linked report and return its climate pages, or "" if unreadable."""
    try:
        content_type, content = await _fetch_content(url)
    except Exception as exc:
        logger.warning(
            f"Linked report could not be fetched: {url}: {exc}",
            extra={"operation": "source_doc_linked_fetch_failed", "url": url},
        )
        return ""
    if "pdf" not in content_type.lower() and not url.lower().split("?")[0].endswith(".pdf"):
        return ""
    text = await asyncio.to_thread(_climate_pages, content)
    logger.info(
        f"Linked report read: {url} ({len(text)} chars)",
        extra={"operation": "source_doc_linked_read", "url": url, "chars": len(text)},
    )
    return text


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

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
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import anthropic
import httpx

from core.local_copies import read_copy
from core.logger import get_logger
from core.model_requests import TOOL_CALL_ATTEMPTS
from core.retry import DataSourceError
from core.textutil import final_counters
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_source_document_data"]

logger = get_logger(__name__)

_TOOL_NAME = "extract_climate_disclosures"
_MODEL_ID = "claude-haiku-5-5"
_MAX_HTML_CHARS = 80_000
_MAX_LINKED_CHARS = 60_000
# Up to two linked documents are read, the company's newest report and a transition
# plan or climate report, each with the room one document would get alone.
_MAX_LINKED_DOCUMENTS = 2
_LINKED_SHARES = (_MAX_LINKED_CHARS, _MAX_LINKED_CHARS)
_MAX_MORE_CHARS = 30_000
# How far after a claim, in characters of page text, its "Read more" link may sit: a
# teaser's link follows it directly, and a link further down belongs to the next card.
_MORE_DISTANCE = 300
# The most text, in characters, that may stand between a claim and its own "Read more"
# link, and the heading tags that mark the start of the next item on a page.
_MORE_GAP = 60
_HEADING = re.compile(r"<h[1-6][\s>]", re.IGNORECASE)

# Kinds of company document a claim page links to, in the order they are read, with
# the words in a link's address or text that mark each. The company's newest annual or
# sustainability report comes first: it holds the latest figures and any assurance
# report. A transition plan, which sets out the route a pledge rests on, comes next,
# and a climate report or CDP response only when there is no plan. Of several
# documents of one kind, the most recent is read.
_DOCUMENT_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "transition plan",
        ("transition-plan", "transition_plan", "transition+plan", "transition plan"),
    ),
    ("report", ("sustainab", "esg", "csrd", "non-financial", "annual", "integrated")),
    ("climate report", ("climate", "tcfd", "cdp")),
)
_READING_ORDER = ("report", "transition plan", "climate report")

# Words that mark the pages of a long report that concern climate.
_PAGE_WORDS = (
    "net zero",
    "net-zero",
    "scope 1",
    "scope 2",
    "scope 3",
    "emission",
    "greenhouse",
    "target",
    "transition plan",
    "decarboni",
    "abatement",
    "carbon",
    "co2",
    "sustainable aviation fuel",
    "renewable",
    "actions and resources",
)

# Phrases that mark an assurance report on sustainability information. Its pages
# are always read, because independent verification is one of the elements
# checked. A financial audit report says "reasonable assurance", so that phrase
# is left out. A page counts only if it also holds the practitioner's conclusion,
# so that a table of contents that lists the report is not taken for it.
_ASSURANCE_WORDS = (
    "limited assurance",
    "assurance engagement",
    "isae 3000",
    "isae 3410",
    "issa 5000",
)
_ASSURANCE_CONCLUSIONS = (
    "nothing has come to our attention",
    "nothing came to our attention",
    "conclusion",
)
_MAX_ASSURANCE_PAGES = 3
# Pages that hold one of the claim's own figures, such as "41%", are read next.
_MAX_FIGURE_PAGES = 3
# Then the page after a figure page when it explains how figures were calculated.
_MAX_NOTE_PAGES = 2
_METHOD_WORDS = ("methodolog", "calculat", "accounting principle", "basis of preparation")

_ANCHOR = re.compile(
    r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", flags=re.IGNORECASE | re.DOTALL
)
_MORE_LABEL = re.compile(
    r"\b(?:read|learn|find out|discover)\b(?:\s+\w+){0,2}?\s+(?:more|about)\b",
    flags=re.IGNORECASE,
)
# Navigation and footers hold "Read more" links that belong to no claim.
_PAGE_CHROME = re.compile(r"<(nav|footer)\b.*?</\1\s*>", flags=re.IGNORECASE | re.DOTALL)
_MAX_PDF_PAGES = 100  # Anthropic document API hard limit
_MARKER = re.compile(r"\[PDF page (\d+)\]")


def _page_ranges(numbers: list[int]) -> str:
    """Write sorted page numbers as ranges: [3, 4, 5, 9] gives "3-5 and 9"."""
    spans: list[str] = []
    start = prev = numbers[0]
    for number in [*numbers[1:], 0]:
        if number == prev + 1:
            prev = number
            continue
        spans.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = number
    return spans[0] if len(spans) == 1 else ", ".join(spans[:-1]) + " and " + spans[-1]


def pages_read_note(document: str, text: str, page_count: int) -> str:
    """Say which pages of a long document were read, from the page markers in its text.

    Args:
        document: The document's address.
        text: The text that was read, with its [PDF page N] markers.
        page_count: The document's number of pages, or 0 if unknown.

    Returns:
        A sentence that starts with a space, or "" when every page was read.
    """
    numbers = sorted({int(n) for n in _MARKER.findall(text)})
    if page_count and len(numbers) >= page_count:
        return ""
    size = f", a PDF of {page_count} pages," if page_count else ","
    if not numbers:
        return f" Of {document}{size} only the opening pages were read."
    return (
        f" Of {document}{size} only PDF pages {_page_ranges(numbers)} were read: the "
        "pages on climate, any assurance report and the pages with the claim's own figures."
    )


# A long annual report can take minutes to download.
_FETCH_TIMEOUT = 180.0

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
                    "Each interim target the document states, as 'YEAR: target', "
                    "followed by the progress the document reports against it, if any: "
                    "'met' or 'missed' only for a target whose year has passed, otherwise "
                    "the latest figure. A target whose year has not come is neither met "
                    "nor missed. Empty if the document states none."
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
                    "Include only elements that the document, or for a long document the "
                    "pages given, does not show. "
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
                    "the pages read do not show, in plain words. Quote what the document says about "
                    "the company's fossil fuel strategy if it says anything. Never name or "
                    "cite a law or a legal provision. Write plain sentences in the third "
                    "person, without field names or capitalised labels."
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

Keep every target, milestone and action with the year or period it belongs to. A \
table or a timeline gives that year in a column or a heading: carry it into the \
summary, as in "by 2040 it plans to exit gas-fired generation". Never state a \
planned action as done.

When the document gives the share of Scope 1, 2 or 3 emissions that a target \
covers, name that target, and give the coverage of all targets together where the \
document states it. Name the target each interim figure belongs to, with the \
boundary the document gives for it.

Quote verbatim the conditions and qualifications of a target, the description of a \
project, and any words that limit a commitment, such as a condition it depends on. \
Keep each condition or qualification with the objective or target it is stated for, \
name that objective, and never apply it to another.

If the text does not show which year or column an action or a figure belongs to, say \
that its year is not shown; never state it as done or current. A target whose year \
has not come is neither met nor missed: say when it falls due and give the progress \
the document reports.

Where the pages state progress since a base year, give it beside what remains to \
be done.

Page numbers printed in the text, in footers or in a table of contents are not the \
markers. Cite only the [PDF page N] marker of the page where the text appears.

Before writing that the pages do not give something, check every page supplied.

For a claim about future environmental performance, such as a net-zero target, \
check the document against the elements that Article 6(2)(d) of the Unfair \
Commercial Practices Directive, as amended by Directive (EU) 2024/825, lists: \
clear, objective, publicly available and verifiable commitments; a detailed and \
realistic implementation plan; measurable and time-bound targets; other elements \
needed to implement it, such as allocation of resources; regular verification by \
an independent third-party expert; and findings of that verification made \
available to consumers. Record which of these the pages read do not show. In the \
summary, describe them in plain words, such as "the pages read show no \
implementation plan" or "the pages read show no independent verification": never \
name or cite the provision or any other law, and never say whether a law is \
breached.

If the document says anything about the company's own fossil fuel strategy, such \
as coal, oil or gas production, a phase-down or an expansion, quote it in the \
summary: it is the company's stated position and belongs beside any record about \
its fossil fuel supply.

An assurance report by an independent practitioner on the company's sustainability \
information is independent verification of what it covers. When the pages include \
one, name in the summary the practitioner, the level of assurance (limited or \
reasonable) and what it covers, and say whether it covers the delivery of the plan \
or only the reported information. If the assured statement includes a transition \
plan, targets or the results against them, by reference or otherwise, say so. Give \
the pages the assured statements cover, as the assurance report states them, and \
say whether the page that holds the claim, or the matter it describes, lies inside \
them. Never write that a document has no independent assurance or verification \
when such a report is in the pages.

Never name a private person in the summary: refer to a document by its title, its \
organisation and its date. Firms and organisations, such as the assurance \
provider, are named.

If the document states what share of Scope 1 emissions falls under an emission \
trading scheme such as the EU ETS, give that share and its year in the summary.

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
    linked_urls: list[str] = []
    linked_read: list[str] = []
    more_url: str | None = None
    more_read = False

    partial = False
    read_notes: list[str] = []
    is_pdf = "pdf" in content_type.lower() or claim.source_url.lower().endswith(".pdf")
    if is_pdf:
        address = claim.source_url.split("#")[0]
        if address not in _page_counts:
            _page_counts[address] = await asyncio.to_thread(_pdf_page_count, content_bytes)
        page_count = _page_counts[address]
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
            # The model sees the pages of a document block without their numbers, so a
            # map of each page's first words gives it the marker to cite.
            page_map = "\n".join(
                f"[PDF page {i + 1}] {' '.join(text.split())[:150]}"
                for i, text in enumerate(await _pages_of(address, content_bytes))
                if text
            )
            if page_map:
                content_blocks.append(
                    {
                        "type": "text",
                        "text": (
                            "PAGE MAP: the first words of each page of the document above, "
                            "with the PDF page number to cite for it.\n" + page_map
                        ),
                    }
                )
            logger.info(
                f"Source document is PDF ({len(content_bytes) // 1024} KB, {page_count} pages)",
                extra={"operation": "source_doc_pdf", "size_kb": len(content_bytes) // 1024},
            )
        else:
            # A long report: read the pages that concern climate, not its first pages,
            # and say that only those pages were read.
            pages = await _pages_of(address, content_bytes)
            text = (
                select_pages(pages, _MAX_HTML_CHARS, True, claim_figures(claim.raw_text))
                or " ".join(pages)[:_MAX_HTML_CHARS]
            )
            partial = True
            read_notes.append(pages_read_note(claim.source_url, text, page_count))
            content_blocks.append(
                {
                    "type": "text",
                    "text": (
                        f"DOCUMENT: {claim.source_url}, a PDF of {page_count} pages. Only "
                        "these pages were read: those that concern climate most, any "
                        "assurance report in it and any page with the claim's own figures, "
                        f"each marked with its PDF page number.\n{text}"
                    ),
                }
            )
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
        candidates = _report_links(html, claim.source_url)
        more_url = _read_more_page(html, claim.source_url, claim.raw_text)
        if more_url:
            more_html = await _read_more_html(more_url)
            if more_html:
                more_read = True
                content_blocks.append(
                    {
                        "type": "text",
                        "text": (
                            f"\nLINKED PAGE: the claim is followed by a link to {more_url}, "
                            "whose text follows.\n"
                            f"{_strip_html(more_html)[:_MAX_MORE_CHARS]}"
                        ),
                    }
                )
                candidates += _report_links(more_html, more_url)
        linked_urls = _choose_reports(candidates)
        source = "the page or the linked page" if more_read else "the page"
        figures = claim_figures(claim.raw_text)
        for url, share in zip(linked_urls, _LINKED_SHARES, strict=False):
            linked_text = await _read_linked_report(url, share, figures)
            if linked_text:
                linked_read.append(url)
                document = _resolved.get(url, url)
                via = f" (through the page {url})" if document != url else ""
                read_notes.append(
                    pages_read_note(
                        document, linked_text, len(_page_texts.get(document.split("#")[0], []))
                    )
                )
                content_blocks.append(
                    {
                        "type": "text",
                        "text": (
                            f"\nLINKED DOCUMENT: {document}, a company document linked from "
                            f"{source}{via}. The pages of it that concern climate, any assurance "
                            "report in it and any page with the claim's own figures follow, "
                            f"each marked with its PDF page number.\n{linked_text}"
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
                    " The page and everything linked from it are the company's own. In "
                    "the summary, say which statements come from the page and which from "
                    "each linked page or document."
                    if linked_read or more_read
                    else ""
                )
                + (
                    " Cite a document's pages as 'PDF page N' with the number of the "
                    "marker. Only the pages given were read from a long or linked "
                    "document: write 'in the pages read' for anything they do not show, "
                    "and never say that a document does not contain something."
                    if linked_read or partial
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
        # A call without a summary is a failed read: sent again, never filled in.
        if tool_block is not None and str(tool_block.input.get("summary") or "").strip():
            break
        tool_block = None

    if tool_block is None:
        raise DataSourceError(
            message="The source document could not be read: the analysis returned no summary.",
            source="SOURCE_DOCUMENT",
            retryable=False,
        )

    extraction: dict[str, Any] = tool_block.input
    supports_claim: bool | None = extraction.get("supports_claim")
    confidence: float = float(extraction.get("confidence", 0.70))
    summary: str = str(extraction["summary"]).strip().replace('\\"', '"')
    # A summary that ends on a quotation mark it never opened is cut, not quoting.
    if summary.count('"') % 2 and summary.endswith('"'):
        summary = summary[:-1].rstrip()
    missing_plan_elements: list[str] = extraction.get("missing_plan_elements", [])
    unread = [url for url in linked_urls if url not in linked_read and url not in _no_document]
    if more_url and not more_read:
        unread.insert(0, more_url)
    if unread:
        summary = (
            f"{summary} The page links to {', '.join(unread)}, which this assessment "
            "could not read."
        )
    summary += "".join(read_notes)

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
        "linked_documents": linked_urls,
        "linked_documents_read": linked_read,
        "linked_page": more_url,
        "linked_page_read": more_read,
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


def _report_links(html: str, page_url: str) -> list[tuple[str, str, int]]:
    """Return the company documents a page links to, as (kind, address, year).

    A climate page often states a claim in a sentence and links to the documents
    that set it out: a transition plan, a sustainability or annual report.

    Args:
        html: The page's HTML.
        page_url: The page's address, for resolving relative links.

    Returns:
        One entry per link whose address or text names a kind of company
        document, in page order, without the address's fragment. The year is
        the latest year the link names, or 0. A link to a web page rather than a
        PDF is kept as well: _read_linked_report follows it to the PDF it offers.
    """
    found: list[tuple[str, str, int]] = []
    for href, inner in _ANCHOR.findall(html):
        if href.lower().startswith(("mailto:", "javascript:", "#", "tel:")):
            continue
        url = urljoin(page_url, href.replace("&amp;", "&")).split("#")[0]
        if url.rstrip("/") == page_url.split("#")[0].rstrip("/"):
            continue
        words = f"{url} {_strip_html(inner)}".lower()
        kind = next(
            (name for name, marks in _DOCUMENT_KINDS if any(mark in words for mark in marks)),
            None,
        )
        if kind:
            found.append((kind, url, _latest_year(words)))
    return found


def _latest_year(text: str) -> int:
    """Return the latest year a link names, reading "FY26" as 2026, or 0.

    A year inside a hexadecimal identifier in the address is not read as one.
    """
    years = [int(y) for y in re.findall(r"(?<![0-9a-f])(20\d\d)(?![0-9a-f])", text)]
    years += [2000 + int(y) for y in re.findall(r"\bfy ?(\d\d)\b", text)]
    return max(years, default=0)


def _choose_reports(candidates: list[tuple[str, str, int]]) -> list[str]:
    """Choose the linked documents to read.

    Kinds are read in _READING_ORDER, and of each kind the most recent document,
    the first in page order on a tie. A document more than two years older than
    the most recent one linked is left out.

    Args:
        candidates: (kind, address, year) for each linked company document.

    Returns:
        Up to _MAX_LINKED_DOCUMENTS addresses.
    """
    latest = max((year for _kind, _url, year in candidates), default=0)
    current = [
        (index, kind, url, year)
        for index, (kind, url, year) in enumerate(candidates)
        if year == 0 or year >= latest - 2
    ]
    chosen: list[str] = []
    for name in _READING_ORDER:
        if name == "climate report" and len(chosen) > 1:
            break
        # Of the same kind and year, a PDF comes before a web page about it.
        of_kind = [
            (year, _is_pdf(url), -index, url) for index, kind, url, year in current if kind == name
        ]
        if of_kind:
            url = max(of_kind)[3]
            if url not in chosen:
                chosen.append(url)
    return chosen[:_MAX_LINKED_DOCUMENTS]


def _is_pdf(url: str) -> bool:
    """Tell whether an address names a PDF."""
    return ".pdf" in url.lower()


def _read_more_page(html: str, page_url: str, claim_text: str) -> str | None:
    """Return the page that a "Read more" link right after the claim opens, if any.

    An index page often gives a claim as a short teaser and sets out its
    substance on the page the teaser's "Read more" link opens, and a claim that
    rests on a document often links it in its own sentence ("verified in our
    EPDs"). A link inside the claim is followed first; otherwise the first
    "Read more" or "Learn all about" link within _MORE_DISTANCE characters after
    the claim. Only a page of the same site is followed; a link to a PDF is left
    to _report_links.

    Args:
        html: The page's HTML.
        page_url: The page's address.
        claim_text: The claim as extracted from the page.

    Returns:
        The address of the page to read, without its fragment, or None.
    """
    anchors: list[tuple[str, str]] = []

    def mark(match: re.Match[str]) -> str:
        anchors.append((match.group(1), _strip_html(match.group(2))))
        return f" \x00{len(anchors) - 1}\x00 "

    marked = _ANCHOR.sub(mark, _PAGE_CHROME.sub(" ", html))
    text = _comparable(_strip_html(_HEADING.sub(" \x01 ", marked)))
    claim = _comparable(claim_text)
    if not claim:
        return None
    start = text.find(claim[:60])
    end = start + len(claim)
    if start < 0:
        tail = text.find(claim[-60:])
        if tail < 0:
            return None
        end = tail + len(claim[-60:])
    begin = max(0, end - len(claim))
    page = page_url.split("#")[0].rstrip("/")

    def target(index: str) -> str | None:
        href, _label = anchors[int(index)]
        url = urljoin(page_url, href.replace("&amp;", "&")).split("#")[0]
        if ".pdf" in url.lower() or _host(url) != _host(page_url) or url.rstrip("/") == page:
            return None
        return url

    # A link inside the claim's own sentence names what the claim rests on.
    for index in re.findall(r"\x00(\d+)\x00", text[begin:end]):
        url = target(index)
        if url:
            return url
    window = text[end : end + _MORE_DISTANCE]
    for match in re.finditer(r"\x00(\d+)\x00", window):
        if not _MORE_LABEL.search(anchors[int(match.group(1))][1]):
            continue
        # A heading or a block of other text between the claim and the link means the
        # link belongs to the next item on the page.
        between = re.sub(r"\x00\d+\x00", "", window[: match.start()])
        if "\x01" in between or len(between.strip()) > _MORE_GAP:
            return None
        return target(match.group(1))
    return None


def _host(url: str) -> str:
    """Return a URL's host without a leading "www."."""
    return urlparse(url).netloc.lower().removeprefix("www.")


def _comparable(text: str) -> str:
    """Return text as two copies of one sentence share it: entities decoded, lower
    case, straight quotes and single spaces."""
    text = unescape(text).lower()
    for curly, straight in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"')):
        text = text.replace(curly, straight)
    return " ".join(text.replace("\u00a0", " ").split())


def _extract_pages(pdf_bytes: bytes) -> list[str]:
    """Return the text of each page of a PDF, whitespace normalised, or [] if unreadable."""
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        # Line breaks are kept, so that a table's heading row, which gives the year of
        # each column, stays a row of its own.
        return [
            "\n".join(
                " ".join(line.split())
                for line in (page.extract_text() or "").splitlines()
                if line.strip()
            )
            for page in reader.pages
        ]
    except Exception:
        return []


# Reading a 700-page report into text takes about 20 seconds, so each PDF is read once
# per run, off the event loop, and every claim chooses its pages from that one reading.
_page_texts: dict[str, list[str]] = {}
_page_locks: dict[str, asyncio.Lock] = {}


async def _pages_of(address: str, pdf_bytes: bytes) -> list[str]:
    """Return the page texts of the PDF at an address, reading it the first time only."""
    lock = _page_locks.setdefault(address, asyncio.Lock())
    async with lock:
        if address not in _page_texts:
            _page_texts[address] = await asyncio.to_thread(_extract_pages, pdf_bytes)
        return _page_texts[address]


def climate_pages(
    pdf_bytes: bytes,
    limit: int = _MAX_LINKED_CHARS,
    assurance: bool = True,
    figures: tuple[str, ...] = (),
) -> str:
    """Return the pages of a PDF that concern climate most, in page order.

    Args:
        pdf_bytes: The PDF.
        limit: The most characters to return.
        assurance: Whether to take first the pages of an assurance report on
            sustainability information that hold its conclusion, up to
            _MAX_ASSURANCE_PAGES of them.
        figures: Figures from the claim, as claim_figures gives them; up to
            _MAX_FIGURE_PAGES pages that hold one are taken next.

    Returns:
        The chosen pages, each marked with its PDF page number, or "" when the
        PDF cannot be read or no page concerns climate.
    """
    return select_pages(_extract_pages(pdf_bytes), limit, assurance, figures)


def select_pages(
    pages: list[str],
    limit: int = _MAX_LINKED_CHARS,
    assurance: bool = True,
    figures: tuple[str, ...] = (),
) -> str:
    """Choose from a PDF's page texts as climate_pages does. Args as for climate_pages."""
    # Phrases are matched across line breaks.
    lowered = [" ".join(text.lower().split()) for text in pages]
    weights = [sum(text.count(word) for word in _PAGE_WORDS) for text in lowered]
    order = sorted((i for i in range(len(pages)) if weights[i]), key=lambda i: -weights[i])
    first: list[int] = []
    if assurance:
        marks = [
            sum(text.count(word) for word in _ASSURANCE_WORDS)
            if any(phrase in text for phrase in _ASSURANCE_CONCLUSIONS)
            else 0
            for text in lowered
        ]
        first = sorted((i for i in range(len(pages)) if marks[i]), key=lambda i: -marks[i])
        first = first[:_MAX_ASSURANCE_PAGES]
    if figures:
        compact = [_percent(text) for text in lowered]
        # A figure counts only on its own: "92%" is not found inside "492%".
        patterns = [re.compile(r"(?<![\d.,])" + re.escape(figure)) for figure in figures]
        with_figures = [
            i
            for i in sorted(range(len(pages)), key=lambda i: -weights[i])
            if i not in first and any(pattern.search(compact[i]) for pattern in patterns)
        ]
        first += with_figures[:_MAX_FIGURE_PAGES]
        # The note that explains how a figure was calculated often follows it.
        notes = [
            i + 1
            for i in with_figures[:_MAX_FIGURE_PAGES]
            if i + 1 < len(pages)
            and i + 1 not in first
            and any(word in lowered[i + 1] for word in _METHOD_WORDS)
        ]
        first += list(dict.fromkeys(notes))[:_MAX_NOTE_PAGES]
    order = first + [i for i in order if i not in first]
    chosen: list[int] = []
    total = 0
    for index in order:
        if total + len(pages[index]) > limit:
            continue
        chosen.append(index)
        total += len(pages[index])
    if not any(weights[i] for i in chosen):
        return ""
    return "\n".join(f"[PDF page {i + 1}] {pages[i]}" for i in sorted(chosen))


# A run reads the same linked report for several claims, so a read is kept for the
# rest of the process.
_linked_reads: dict[tuple[str, int, tuple[str, ...]], str] = {}


def claim_figures(text: str) -> tuple[str, ...]:
    """Return the figures in a claim that can find its page in a report.

    Percentages and decimal numbers only, written without a space before "%": a
    bare year or round number is on too many pages to point at one.

    Args:
        text: The claim.

    Returns:
        The figures, lower case, in the order they appear, without repeats.
    """
    found = re.findall(r"\d+(?:[.,]\d+)?%|\b\d+[.,]\d+\b", _percent(text))
    return tuple(dict.fromkeys(figure.lower() for figure in found))


def _percent(text: str) -> str:
    """Write a percentage one way: "41 %", "41 percent" and "41 per cent" as "41%"."""
    return re.sub(r"(\d)\s*(?:%|percent\b|per cent\b)", r"\1%", text, flags=re.IGNORECASE)


async def _read_more_html(url: str) -> str:
    """Fetch the page a "Read more" link opens and return its HTML, or "" if unreadable."""
    try:
        content_type, content = await _fetch_content(url)
    except Exception as exc:
        logger.warning(
            f"Linked page could not be fetched: {url}: {exc}",
            extra={"operation": "source_doc_more_fetch_failed", "url": url},
        )
        return ""
    if "html" not in content_type.lower():
        return ""
    return content.decode("utf-8", errors="replace")


# A linked web page about a report, and the PDF of the report it was followed to.
_resolved: dict[str, str] = {}
# Linked web pages that offer no report: pages, not documents left unread.
_no_document: set[str] = set()


async def _read_linked_report(
    url: str, limit: int = _MAX_LINKED_CHARS, figures: tuple[str, ...] = ()
) -> str:
    """Fetch a linked report and return its climate and assurance pages, or "" if unreadable."""
    key = (url, limit, figures)
    if key in _linked_reads:
        return _linked_reads[key]
    try:
        content_type, content = await _fetch_content(url)
    except Exception as exc:
        logger.warning(
            f"Linked report could not be fetched: {url}: {exc}",
            extra={"operation": "source_doc_linked_fetch_failed", "url": url},
        )
        return ""
    if "pdf" not in content_type.lower() and not url.lower().split("?")[0].endswith(".pdf"):
        # A web page about a report: read the PDF of that report it links to, if any.
        if "html" not in content_type.lower():
            _no_document.add(url)
            return ""
        page = content.decode("utf-8", errors="replace")
        pdfs = _choose_reports([c for c in _report_links(page, url) if _is_pdf(c[1])])
        if not pdfs:
            _no_document.add(url)
            return ""
        _resolved[url] = pdfs[0]
        try:
            content_type, content = await _fetch_content(pdfs[0])
        except Exception as exc:
            logger.warning(
                f"Linked report could not be fetched: {pdfs[0]}: {exc}",
                extra={"operation": "source_doc_linked_fetch_failed", "url": pdfs[0]},
            )
            return ""
        url = pdfs[0]
    text = select_pages(await _pages_of(url.split("#")[0], content), limit, True, figures)
    if text:
        _linked_reads[key] = text
    logger.info(
        f"Linked report read: {url} ({len(text)} chars)",
        extra={"operation": "source_doc_linked_read", "url": url, "chars": len(text)},
    )
    return text


_page_counts: dict[str, int] = {}


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF, or 0 if unreadable."""
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        return len(reader.pages)
    except Exception:
        return 0


# A run reads the same document for several claims, often at the same time. Each address
# is fetched once per process: the first claim fetches it, the others wait for that fetch
# and share its result, so one document cannot be read for one claim and missing for
# another.
_fetched: dict[str, tuple[str, bytes]] = {}
_fetch_locks: dict[str, asyncio.Lock] = {}


async def _fetch_content(url: str) -> tuple[str, bytes]:
    """Fetch a URL once per run and return (content_type, raw_bytes).

    Args:
        url: The URL to fetch. Its fragment is ignored.

    Returns:
        Tuple of (content_type, response_body_bytes).

    Raises:
        DataSourceError: On HTTP 4xx/5xx.
    """
    copy = read_copy(url)
    if copy is not None:
        return copy
    address = url.split("#")[0]
    lock = _fetch_locks.setdefault(address, asyncio.Lock())
    async with lock:
        if address not in _fetched:
            try:
                _fetched[address] = await _download(address)
            except httpx.TimeoutException:
                # One retry: a slow server is the usual cause, not a missing document.
                _fetched[address] = await _download(address)
        return _fetched[address]


async def _download(url: str) -> tuple[str, bytes]:
    """Download a URL with the index's user agent and return (content_type, raw_bytes)."""
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
        final_counters(html),
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

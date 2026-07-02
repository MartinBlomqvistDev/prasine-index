"""Top-level pipeline orchestrator for the Prasine Index system.

Wires all seven agents into the complete claim verification workflow and handles
the database persistence layer between agent steps. Each agent step is isolated:
the orchestrator commits its trace and any produced models to PostgreSQL before
invoking the next agent, so that a failure at any stage leaves a complete audit
trail of everything that succeeded.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import anthropic
import httpx
from playwright.async_api import async_playwright
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from agents.context_agent import ContextAgent, ContextInput
from agents.discovery_agent import DiscoveryAgent, extract_relevant_links
from agents.extraction_agent import ExtractionAgent, ExtractionInput
from agents.judge_agent import JudgeAgent, JudgeInput
from agents.lobbying_agent import LobbyingAgent, LobbyingInput
from agents.report_agent import ReportAgent, ReportInput
from agents.verification_agent import VerificationAgent, VerificationInput
from core.database import get_session
from core.logger import bind_trace_context, get_logger
from core.textutil import html_to_text as _html_to_text
from models.claim import Claim, ClaimLifecycle, ClaimStatus, SourceType
from models.company import Company
from models.evidence import VerificationResult
from models.score import GreenwashingScore
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "Pipeline",
    "PipelineConfig",
    "PipelineResult",
]

_MAX_FETCH_CHARS = 40_000

# PDFs get a higher cap: a single investor-facing ESG PDF often IS the whole
# assessment source, and claims beyond a 40k cut-off would be invisible.
# 150k chars ≈ 40k tokens — comfortably within Haiku's extraction context.
_MAX_PDF_CHARS = 150_000


def _extract_pdf_text(content: bytes) -> str:
    """Extract plain text from a PDF document using pypdf.

    Iterates over all pages and joins their extracted text with newlines.
    Output is capped at _MAX_FETCH_CHARS by the caller.

    Args:
        content: Raw PDF bytes.

    Returns:
        Extracted plain text, or an empty string if extraction fails.
    """
    try:
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(content))
        parts: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text.strip())
        return "\n\n".join(parts)
    except Exception as exc:
        get_logger(__name__).warning(
            f"_extract_pdf_text: extraction failed — {exc}",
            extra={"operation": "pdf_extraction_failed", "error": str(exc)},
        )
        return ""


def _is_pdf(response: httpx.Response) -> bool:
    """Return True if the HTTP response contains a PDF document."""
    ct = response.headers.get("content-type", "").lower()
    return "pdf" in ct or response.content[:4] == b"%PDF"


# Below this character count, httpx content is treated as a JS-rendered SPA shell
# and Playwright takes over.
_SPA_THRESHOLD = 500

_FETCH_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PrasineIndex/1.0; "
        "+https://github.com/MartinBlomqvistDev/prasine-index)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "sv,en-GB;q=0.9,en;q=0.8",
}


async def _fetch_pages(
    source_url: str,
    http_client: httpx.AsyncClient,
    max_subpages: int,
) -> list[tuple[str, str]]:
    """Fetch an entry URL and its sustainability subpages.

    Tries httpx first (fast, no overhead). If the entry page yields fewer than
    _SPA_THRESHOLD chars after HTML-to-text, the page is assumed to be a
    JS-rendered SPA and Playwright takes over for the full crawl.

    Args:
        source_url: Entry-point URL.
        http_client: Shared async HTTP client.
        max_subpages: Maximum additional subpages to follow.

    Returns:
        List of (url, extracted_text) pairs, entry page first.

    Raises:
        RuntimeError: If the entry page cannot be fetched.
    """
    try:
        resp = await http_client.get(source_url, headers=_FETCH_HEADERS)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Failed to fetch {source_url}: {exc}") from exc

    # PDF — extract text directly, no subpage discovery.
    if _is_pdf(resp):
        get_logger(__name__).info(
            f"_fetch_pages: PDF detected at {source_url} — extracting text with pypdf",
            extra={"operation": "pipeline_pdf_fetch", "url": source_url},
        )
        pdf_text = _extract_pdf_text(resp.content)[:_MAX_PDF_CHARS]
        return [(source_url, pdf_text)] if pdf_text else []

    raw_html = resp.text
    entry_text = _html_to_text(raw_html)[:_MAX_FETCH_CHARS]

    if len(entry_text) < _SPA_THRESHOLD:
        _log = get_logger(__name__)
        _log.info(
            f"_fetch_pages: thin content ({len(entry_text)} chars) at {source_url} "
            "— switching to Playwright for JS rendering",
            extra={"operation": "pipeline_playwright_fallback", "url": source_url},
        )
        try:
            return await _fetch_pages_playwright(source_url, raw_html, max_subpages)
        except Exception as exc:
            # Playwright unavailable (browser not installed, launch failure)
            # must not kill the whole assessment — degrade to whatever the
            # static fetch produced and let extraction judge its usefulness.
            _log.warning(
                f"_fetch_pages: Playwright failed ({exc}) — falling back to "
                f"static httpx content ({len(entry_text)} chars)",
                extra={"operation": "pipeline_playwright_failed", "url": source_url},
            )

    # Static site path — httpx for all subpages, fetched concurrently.
    pages: list[tuple[str, str]] = []
    if entry_text:
        pages.append((source_url, entry_text))

    seen: set[str] = {source_url.rstrip("/")}
    sub_urls: list[str] = []
    for u in extract_relevant_links(raw_html, source_url, max_links=max_subpages):
        if u not in seen:
            seen.add(u)
            sub_urls.append(u)

    semaphore = asyncio.Semaphore(5)

    async def _fetch_sub(sub_url: str) -> tuple[str, str] | None:
        async with semaphore:
            try:
                sub_resp = await http_client.get(sub_url, headers=_FETCH_HEADERS)
                sub_resp.raise_for_status()
                sub_text = _html_to_text(sub_resp.text)[:_MAX_FETCH_CHARS]
                return (sub_url, sub_text) if sub_text else None
            except Exception as exc:
                get_logger(__name__).warning(
                    f"_fetch_pages: skipping subpage {sub_url}: {exc}",
                    extra={"operation": "pipeline_subpage_failed", "url": sub_url},
                )
                return None

    fetched = await asyncio.gather(*(_fetch_sub(u) for u in sub_urls))
    pages.extend(page for page in fetched if page is not None)

    return pages


async def _fetch_pages_playwright(
    source_url: str,
    server_html: str,
    max_subpages: int,
) -> list[tuple[str, str]]:
    """Render an entry URL and its subpages with a headless Chromium browser.

    Used when httpx returns thin content from a JS-rendered SPA. Launches one
    browser instance, renders the entry page (waiting 3 s for hydration), then
    follows subpage links and renders each one in sequence.

    Link extraction prefers the rendered DOM over the server HTML, falling back
    to server HTML when the rendered DOM yields fewer links (handles SPAs where
    the nav links are already in the server response for SEO).

    Args:
        source_url: Entry-point URL.
        server_html: Raw HTML from the initial httpx fetch — used as fallback
            source for link extraction.
        max_subpages: Maximum subpages to render.

    Returns:
        List of (url, extracted_text) pairs.
    """
    _log = get_logger(__name__)
    pages: list[tuple[str, str]] = []
    seen: set[str] = {source_url.rstrip("/")}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_FETCH_HEADERS["User-Agent"],
            locale="en-GB",
        )
        try:
            # Render entry page and wait for JS hydration.
            page = await ctx.new_page()
            await page.goto(source_url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3_000)
            rendered_html = await page.content()
            entry_text = _html_to_text(rendered_html)[:_MAX_FETCH_CHARS]
            if entry_text:
                pages.append((source_url, entry_text))
            await page.close()

            # Prefer rendered-DOM links (catches JS-injected <a> tags); fall back
            # to server HTML links when the server already has them for SEO.
            rendered_links = list(
                extract_relevant_links(rendered_html, source_url, max_links=max_subpages)
            )
            server_links = list(
                extract_relevant_links(server_html, source_url, max_links=max_subpages)
            )
            sub_urls = rendered_links if len(rendered_links) >= len(server_links) else server_links

            for sub_url in sub_urls:
                if sub_url in seen:
                    continue
                seen.add(sub_url)
                try:
                    sub_page = await ctx.new_page()
                    await sub_page.goto(sub_url, wait_until="domcontentloaded", timeout=30_000)
                    await sub_page.wait_for_timeout(2_000)
                    sub_text = _html_to_text(await sub_page.content())[:_MAX_FETCH_CHARS]
                    if sub_text:
                        pages.append((sub_url, sub_text))
                        _log.info(
                            f"_fetch_pages_playwright: rendered {sub_url}",
                            extra={"operation": "pipeline_playwright_subpage", "url": sub_url},
                        )
                    await sub_page.close()
                except Exception as exc:
                    _log.warning(
                        f"_fetch_pages_playwright: skipping {sub_url}: {exc}",
                        extra={
                            "operation": "pipeline_playwright_subpage_failed",
                            "url": sub_url,
                        },
                    )
        finally:
            await browser.close()

    return pages


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Claim priority scoring (used by run_from_url to pick the best N claims)
# ---------------------------------------------------------------------------

# Category priority — higher = more verifiable / higher greenwashing risk.
_CATEGORY_WEIGHT: dict[str, int] = {
    "NET_ZERO_TARGET": 10,
    "CARBON_NEUTRAL": 9,
    "EMISSIONS_REDUCTION": 8,
    "SCIENCE_BASED_TARGETS": 8,
    "RENEWABLE_ENERGY": 6,
    "SUSTAINABLE_SUPPLY_CHAIN": 5,
    "CIRCULAR_ECONOMY": 4,
    "BIODIVERSITY": 3,
    "OTHER": 1,
}

# Regex patterns that indicate a specific, verifiable claim.
_SPECIFICITY_PATTERNS: list[re.Pattern[str]] = [
    # Large numbers require a thousands separator or 5+ digits so bare year
    # targets (2029) don't double-count — years have their own pattern below.
    re.compile(r"\d{1,3}[,\s]\d{3}|\d{5,}"),  # large numbers (e.g. 200,000)
    re.compile(r"\d+\s*%"),  # percentages
    re.compile(r"20[2-9]\d"),  # year targets (2020-2099)
    re.compile(r"\bzero\b|\bnoll\b", re.I),  # zero-emissions language
    re.compile(r"\b100\s*%"),  # 100% claims
    re.compile(r"\bfirst\b|\bförst\b|\bworld.s\b", re.I),  # superlatives
    re.compile(r"\bccs\b|\bcapture\b|\binfångning\b|\binfangning\b", re.I),  # CCS
    re.compile(r"\bhydrogen\b|\bvätgas\b", re.I),  # hydrogen
    re.compile(r"\bnet.zero\b|\bnetto.*noll\b|\bnettonoll\b", re.I),  # net-zero
    re.compile(r"\bscope [123]\b", re.I),  # GHG scopes
]


# Claims scoring at or below this threshold are generic filler (category=OTHER,
# no specificity signals). They are filtered out before the full pipeline runs.
# Fallback: if ALL claims score below this, the filter is bypassed so the
# pipeline doesn't return empty results for legitimate but weakly-cached pages.
_MIN_CLAIM_PRIORITY = 2

_HAS_LARGE_NUMBER = re.compile(r"\d{1,3}[,\s]\d{3}|\d{5,}")
_HAS_YEAR = re.compile(r"20[2-9]\d")
_HAS_TECHNOLOGY = re.compile(
    r"\bccs\b|\bcapture\b|\binfångning\b|\binfangning\b|\bhydrogen\b|\bvätgas\b"
    r"|\bfånga\b|\bfanga\b|\bnettonoll\b|\bnet.zero\b",
    re.I,
)


def _deduplicate_claims(claims: list[Claim], containment_threshold: float = 0.80) -> list[Claim]:
    """Remove near-duplicate claims using token containment.

    When the same claim appears on multiple pages with minor wording variations,
    keeps the most specific (longest) version and discards near-duplicates.
    Two claims are duplicates if ≥80% of the shorter claim's tokens appear in
    the longer one — this catches both exact repeats and truncated variants.
    """

    def _tokens(claim: Claim) -> frozenset[str]:
        text = claim.normalised_text or claim.raw_text or ""
        return frozenset(w for w in text.split() if len(w) >= 3)

    by_length = sorted(claims, key=lambda c: len(c.raw_text or ""), reverse=True)
    kept: list[tuple[Claim, frozenset[str]]] = []
    for candidate in by_length:
        candidate_tokens = _tokens(candidate)
        if not candidate_tokens:
            kept.append((candidate, candidate_tokens))
            continue
        duplicate = False
        for _, kept_tokens in kept:
            if not kept_tokens:
                continue
            overlap = len(candidate_tokens & kept_tokens)
            shorter = min(len(candidate_tokens), len(kept_tokens))
            if overlap / shorter >= containment_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append((candidate, candidate_tokens))
    return [c for c, _ in kept]


_MAX_CLAIMS_PER_CATEGORY = 2


def _diversify_claims(claims: list[Claim], max_claims: int) -> list[Claim]:
    """Select up to max_claims with category diversity and a per-category cap.

    Claims must already be sorted by priority (highest first). Each category
    contributes at most _MAX_CLAIMS_PER_CATEGORY claims — preventing a
    dominant category (e.g. NET_ZERO_TARGET) from consuming all Opus slots
    when a company repeats the same claim type across multiple pages.
    """
    selected: list[Claim] = []
    category_counts: dict[str, int] = {}

    for claim in claims:
        if len(selected) >= max_claims:
            break
        cat = claim.claim_category.value
        if category_counts.get(cat, 0) < _MAX_CLAIMS_PER_CATEGORY:
            category_counts[cat] = category_counts.get(cat, 0) + 1
            selected.append(claim)

    return selected


def _claim_priority_score(claim: Claim) -> int:
    """Return a priority score for a claim — higher means more worth verifying.

    Combines category weight with text specificity heuristics. A compound
    bonus (+5) is awarded when a claim has both a specific quantity AND a year
    target — this combination (e.g. "capture 200,000 tonnes from 2029") marks
    the most concretely verifiable claims and must beat vague headings.
    """
    category_score = _CATEGORY_WEIGHT.get(claim.claim_category.value, 1)
    text = (claim.raw_text or "") + " " + (claim.normalised_text or "")
    specificity = sum(1 for p in _SPECIFICITY_PATTERNS if p.search(text))
    # Compound bonus: quantity + year = maximally verifiable commitment.
    compound = 5 if (_HAS_LARGE_NUMBER.search(text) and _HAS_YEAR.search(text)) else 0
    # Technology bonus: CCS/hydrogen/net-zero in the claim text indicates high risk.
    tech = 3 if _HAS_TECHNOLOGY.search(text) else 0
    return category_score + specificity + compound + tech


class PipelineConfig(BaseModel):
    """Configuration for a Pipeline instance.

    Attributes:
        extraction_model: Anthropic model ID for the Extraction Agent.
        judge_model: Anthropic model ID for the Judge Agent.
        report_model: Anthropic model ID for the Report Agent.
        persist_traces: Whether to write AgentTrace rows to the database.
            Set False in eval runs to avoid polluting the trace log.
        persist_claims: Whether to write Claim rows to the database.
            Set False in eval runs.
    """

    model_config = ConfigDict(from_attributes=True)

    extraction_model: str = Field(default="claude-haiku-4-5-20251001")
    judge_model: str = Field(default="claude-opus-4-8")
    report_model: str = Field(default="claude-sonnet-5")
    persist_traces: bool = Field(default=True)
    persist_claims: bool = Field(default=True)


class PipelineResult(BaseModel):
    """Complete result of a full pipeline run for a single claim.

    Attributes:
        claim: The extracted and assessed claim.
        score: The Judge Agent's greenwashing verdict.
        report_markdown: The publication-ready report.
        traces: All AgentTrace records from each pipeline step.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(..., description="The extracted and assessed claim.")
    score: GreenwashingScore = Field(..., description="The greenwashing verdict.")
    report_markdown: str = Field(..., description="Publication-ready report in Markdown.")
    traces: list[AgentTrace] = Field(
        default_factory=list,
        description="All AgentTrace records from each pipeline step.",
    )


class Pipeline:
    """Orchestrates the full 7-agent Prasine Index claim verification workflow.

    Accepts either a :py:class:`~models.company.Company` to run the full
    discovery-to-report workflow, or a pre-built
    :py:class:`~agents.extraction_agent.ExtractionInput` to skip the Discovery
    Agent and inject a document directly (used in the eval harness and the
    FastAPI POST endpoint).

    Each agent step is executed sequentially in the order defined by the
    pipeline architecture. The Verification Agent's internal LangGraph graph
    handles parallelism for the data source queries. All other agent steps are
    single-step operations.

    Between agent steps, produced models (Claims, Evidence, Scores, Traces)
    are persisted to PostgreSQL when ``config.persist_claims`` and
    ``config.persist_traces`` are True, ensuring that a failure at any stage
    leaves a queryable audit trail.

    Attributes:
        _config: Pipeline configuration.
        _anthropic_client: Shared Anthropic SDK client.
        _http_client: Shared httpx client.
        _extraction_agent: Extraction Agent instance.
        _context_agent: Context Agent instance.
        _verification_agent: Verification Agent instance.
        _lobbying_agent: Lobbying Agent instance.
        _judge_agent: Judge Agent instance.
        _report_agent: Report Agent instance.
        _discovery_agent: Discovery Agent instance.
    """

    def __init__(
        self,
        config: PipelineConfig | None = None,
        anthropic_client: anthropic.AsyncAnthropic | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialise the pipeline and all agent instances.

        Args:
            config: Pipeline configuration. Defaults to :py:class:`PipelineConfig`
                with production settings if not provided.
            anthropic_client: Shared Anthropic client. Created internally if
                not provided.
            http_client: Shared httpx client. Created internally if not provided.
        """
        self._config = config or PipelineConfig()
        self._owns_anthropic = anthropic_client is None
        self._owns_http = http_client is None

        # Per-run failure accounting, reset at the start of each run_* call.
        # Callers (run_assessment.py) read these after a run to disclose
        # incomplete claims and partial audit trails in the published output.
        self.last_run_failed_claims: list[str] = []
        self.last_run_persist_failures: int = 0

        self._anthropic_client = anthropic_client or anthropic.AsyncAnthropic()
        self._http_client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )

        self._extraction_agent = ExtractionAgent(
            client=self._anthropic_client,
            model_id=self._config.extraction_model,
        )
        self._context_agent = ContextAgent()
        self._verification_agent = VerificationAgent(client=self._anthropic_client)
        self._lobbying_agent = LobbyingAgent()
        self._judge_agent = JudgeAgent(
            client=self._anthropic_client,
            model_id=self._config.judge_model,
        )
        self._report_agent = ReportAgent(
            client=self._anthropic_client,
            model_id=self._config.report_model,
        )
        self._discovery_agent = DiscoveryAgent(http_client=self._http_client)

    async def aclose(self) -> None:
        """Release all owned client resources.

        Call this during application shutdown or at the end of a batch run.
        Clients provided at construction time are not closed.
        """
        if self._owns_anthropic:
            await self._anthropic_client.close()
        if self._owns_http:
            await self._http_client.aclose()

    async def run_from_document(
        self,
        extraction_input: ExtractionInput,
    ) -> list[PipelineResult]:
        """Run the pipeline from a pre-fetched document, skipping Discovery.

        Used by the FastAPI endpoint and the eval harness. The caller provides
        an :py:class:`~agents.extraction_agent.ExtractionInput` directly,
        allowing the pipeline to be tested or triggered manually without
        needing the Discovery Agent's change-detection infrastructure.

        Multiple claims may be extracted from a single document; a
        :py:class:`PipelineResult` is produced for each.

        Args:
            extraction_input: The document and metadata to process.

        Returns:
            List of :py:class:`PipelineResult` instances, one per extracted claim.
        """
        self.last_run_failed_claims = []
        self.last_run_persist_failures = 0

        logger.info(
            "Pipeline starting from document",
            extra={
                "operation": "pipeline_start",
                "source_url": extraction_input.source_url,
            },
        )

        if not extraction_input.raw_content:
            extraction_input = await self._fetch_and_populate(extraction_input)

        extraction_result = await self._extraction_agent.run(extraction_input)
        await self._persist_trace(extraction_result.trace)

        if not extraction_result.claims:
            logger.info(
                "Pipeline complete: no claims extracted",
                extra={"operation": "pipeline_no_claims"},
            )
            return []

        results: list[PipelineResult] = []
        for claim in extraction_result.claims:
            result = await self._run_claim_pipeline(claim)
            if result is not None:
                results.append(result)
            else:
                self.last_run_failed_claims.append((claim.raw_text or "")[:120])

        return results

    async def run_discovery(self, company: Company) -> list[PipelineResult]:
        """Run the full pipeline including Discovery for a company.

        Checks all registered sources for new content and runs the complete
        pipeline for each discovered document.

        Args:
            company: The company to check.

        Returns:
            List of :py:class:`PipelineResult` instances for all new claims found.
        """
        discovery_result = await self._discovery_agent.run(company)
        await self._persist_trace(discovery_result.trace)

        if not discovery_result.documents_found:
            return []

        all_results: list[PipelineResult] = []
        for doc in discovery_result.documents_found:
            results = await self.run_from_document(doc.to_extraction_input())
            all_results.extend(results)

        return all_results

    async def run_from_url(
        self,
        company_id: uuid.UUID,
        source_url: str,
        source_type: SourceType = SourceType.IR_PAGE,
        max_subpages: int = 20,
        max_claims: int = 7,
    ) -> list[PipelineResult]:
        """Fetch a URL, discover relevant sustainability subpages, run pipeline on top claims.

        Strategy: extraction is cheap (one LLM call per page); verification +
        judge + report are expensive.  This method therefore runs extraction
        across *all* discovered pages first, ranks every extracted claim by
        category priority and text specificity, then runs the full expensive
        pipeline on only the top *max_claims* claims.  This guarantees that a
        CCS target page or net-zero blog post — even if linked two levels deep —
        beats vague "responsible business" copy from the landing page.

        Args:
            company_id: UUID of the company being assessed.
            source_url: Entry-point URL — the main sustainability or IR page.
            source_type: Source type applied to all discovered pages.
            max_subpages: Maximum number of additional subpages to fetch.
            max_claims: Maximum number of claims to run through the full
                verification + judge + report pipeline.  Controls token spend.

        Returns:
            List of :py:class:`PipelineResult` for the top *max_claims* claims.
        """
        self.last_run_failed_claims = []
        self.last_run_persist_failures = 0

        # --- Phase 1: fetch all pages (cheap; Playwright fallback for SPAs) ---
        logger.info(
            f"run_from_url: fetching {source_url}",
            extra={"operation": "pipeline_run_from_url", "url": source_url},
        )
        pages = await _fetch_pages(source_url, self._http_client, max_subpages)
        logger.info(
            f"run_from_url: {len(pages)} page(s) fetched for {source_url}",
            extra={"operation": "pipeline_run_from_url_pages", "count": len(pages)},
        )

        # --- Phase 2: extract claims from all pages (cheap) ---
        all_claims: list[Claim] = []
        for page_url, page_content in pages:
            extraction_input = ExtractionInput(
                trace_id=uuid.uuid4(),
                company_id=company_id,
                source_url=page_url,
                source_type=source_type,
                raw_content=page_content,
            )
            extraction_result = await self._extraction_agent.run(extraction_input)
            await self._persist_trace(extraction_result.trace)
            all_claims.extend(extraction_result.claims)

        if not all_claims:
            return []

        # --- Phase 2b: deduplicate near-identical claims across pages ---
        all_claims = _deduplicate_claims(all_claims)

        # --- Phase 3: rank claims, filter generics, keep top N ---
        ranked = sorted(all_claims, key=_claim_priority_score, reverse=True)
        filtered = [c for c in ranked if _claim_priority_score(c) >= _MIN_CLAIM_PRIORITY]
        if not filtered:
            logger.warning(
                "run_from_url: all extracted claims scored below minimum threshold "
                f"({_MIN_CLAIM_PRIORITY}); falling back to top-ranked unfiltered claims. "
                "Consider providing --claim directly or using a more specific URL.",
                extra={"operation": "pipeline_claims_generic_fallback"},
            )
            filtered = ranked
        selected = _diversify_claims(filtered, max_claims)

        logger.info(
            f"run_from_url: {len(all_claims)} claims extracted, "
            f"{len(filtered)} passed quality filter, "
            f"running top {len(selected)} through full pipeline",
            extra={
                "operation": "pipeline_claims_selected",
                "total": len(all_claims),
                "selected": len(selected),
            },
        )

        # --- Phase 4: full pipeline on top claims (expensive) ---
        all_results: list[PipelineResult] = []
        for claim in selected:
            result = await self._run_claim_pipeline(claim)
            if result is not None:
                all_results.append(result)
            else:
                self.last_run_failed_claims.append((claim.raw_text or "")[:120])

        if self.last_run_failed_claims:
            logger.warning(
                f"run_from_url: {len(self.last_run_failed_claims)} of {len(selected)} "
                "claim(s) failed and are excluded from the results",
                extra={
                    "operation": "pipeline_claims_failed",
                    "failed": len(self.last_run_failed_claims),
                    "attempted": len(selected),
                },
            )

        return all_results

    async def preview_claims_from_url(
        self,
        company_id: uuid.UUID,
        source_url: str,
        source_type: SourceType = SourceType.IR_PAGE,
        max_subpages: int = 20,
        max_claims: int = 7,
    ) -> list[Claim]:
        """Fetch a URL and return ranked extracted claims WITHOUT running verification/judge/report.

        Runs phases 1–3 of run_from_url (fetch, extract, rank) at Haiku cost (~$0.01)
        so the caller can review discovered claims before committing to a full Opus run.

        Args:
            company_id: UUID of the company being assessed.
            source_url: Entry-point URL.
            source_type: Source type applied to all discovered pages.
            max_subpages: Maximum number of additional subpages to fetch.
            max_claims: Maximum number of top-ranked claims to return.

        Returns:
            Ranked list of extracted :py:class:`~models.claim.Claim` objects.
        """
        pages = await _fetch_pages(source_url, self._http_client, max_subpages)

        all_claims: list[Claim] = []
        for page_url, page_content in pages:
            extraction_input = ExtractionInput(
                trace_id=uuid.uuid4(),
                company_id=company_id,
                source_url=page_url,
                source_type=source_type,
                raw_content=page_content,
            )
            extraction_result = await self._extraction_agent.run(extraction_input)
            all_claims.extend(extraction_result.claims)

        deduped = _deduplicate_claims(all_claims)
        ranked = sorted(deduped, key=_claim_priority_score, reverse=True)
        filtered = [c for c in ranked if _claim_priority_score(c) >= _MIN_CLAIM_PRIORITY]
        if not filtered:
            logger.warning(
                "preview_claims_from_url: all extracted claims scored below minimum threshold; "
                "returning unfiltered top claims. Consider a more specific URL.",
                extra={"operation": "pipeline_claims_generic_fallback"},
            )
            filtered = ranked
        return _diversify_claims(filtered, max_claims)

    async def _run_claim_pipeline(self, claim: Claim) -> PipelineResult | None:
        """Run agents 2–7 for a single extracted claim.

        Executes Context → Verification (parallel, via LangGraph) → Lobbying
        → Judge → Report in sequence. Each step's trace is persisted before
        the next step begins.

        Args:
            claim: The extracted claim to process.

        Returns:
            A :py:class:`PipelineResult`, or None if a critical step fails.
        """
        traces: list[AgentTrace] = []

        bind_trace_context(
            trace_id=claim.trace_id,
            claim_id=claim.id,
            agent_name=AgentName.CONTEXT.value,
        )

        try:
            # Step 1: Context
            context_result = await self._context_agent.run(
                ContextInput(claim=claim, company_id=claim.company_id)
            )
            traces.append(context_result.trace)
            await self._persist_trace(context_result.trace)
            await self._persist_claim(claim)

            # Step 2: Verification (LangGraph parallel fan-out)
            verification_result, verification_trace = await self._verification_agent.run(
                VerificationInput(
                    claim=claim,
                    context=context_result.context,
                )
            )
            traces.append(verification_trace)
            await self._persist_trace(verification_trace)
            await self._persist_evidence(verification_result)

            # Step 3: Lobbying (non-fatal if skipped)
            lobbying_result = await self._lobbying_agent.run(
                LobbyingInput(
                    claim=claim,
                    company=context_result.context.company,
                )
            )
            traces.append(lobbying_result.trace)
            await self._persist_trace(lobbying_result.trace)

            # Step 4: Judge
            judge_result = await self._judge_agent.run(
                JudgeInput(
                    claim=claim,
                    context=context_result.context,
                    verification=verification_result,
                    lobbying=lobbying_result.record,
                )
            )
            traces.append(judge_result.trace)
            await self._persist_trace(judge_result.trace)
            await self._persist_score(judge_result.score)
            await self._transition_claim_status(
                claim=claim,
                to_status=ClaimStatus.SCORED,
                transitioned_by=AgentName.JUDGE.value,
            )

            # Step 5: Report
            report_result = await self._report_agent.run(
                ReportInput(
                    claim=claim,
                    context=context_result.context,
                    verification=verification_result,
                    lobbying=lobbying_result.record,
                    score=judge_result.score,
                )
            )
            traces.append(report_result.trace)
            await self._persist_trace(report_result.trace)
            await self._persist_report(claim, report_result.report_markdown)
            await self._transition_claim_status(
                claim=claim,
                to_status=ClaimStatus.PUBLISHED,
                transitioned_by=AgentName.REPORT.value,
            )

            logger.info(
                f"Pipeline complete for claim {claim.id}: "
                f"{judge_result.score.verdict.value} (score={judge_result.score.score:.1f})",
                extra={
                    "operation": "pipeline_complete",
                    "verdict": judge_result.score.verdict.value,
                    "score": judge_result.score.score,
                },
            )

            return PipelineResult(
                claim=claim,
                score=judge_result.score,
                report_markdown=report_result.report_markdown,
                traces=traces,
            )

        except Exception as exc:
            logger.error(
                f"Pipeline failed for claim {claim.id}: {exc}",
                exc_info=True,
                extra={
                    "operation": "pipeline_failed",
                    "error_type": type(exc).__name__,
                },
            )
            # Persist a FAILURE trace so trace_log records failed claims too —
            # without this, the audit trail only contains successful steps
            # (survivorship bias in observability).
            failure_trace = AgentTrace(
                trace_id=claim.trace_id,
                claim_id=claim.id,
                agent=AgentName.PIPELINE,
                outcome=AgentOutcome.FAILURE,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                error_type=type(exc).__name__,
                error_message=str(exc)[:500],
                input_schema="models.claim.Claim",
                output_schema=None,
                metadata={"claim_preview": (claim.raw_text or "")[:120]},
            )
            with contextlib.suppress(Exception):
                await self._persist_trace(failure_trace)
            with contextlib.suppress(Exception):
                await self._transition_claim_status(
                    claim=claim,
                    to_status=ClaimStatus.FAILED,
                    transitioned_by=type(exc).__name__,
                )
            return None

    async def _fetch_and_populate(self, extraction_input: ExtractionInput) -> ExtractionInput:
        """Fetch source_url and return a new ExtractionInput with raw_content populated.

        Called when an ExtractionInput arrives without raw_content — i.e. the
        caller provided a URL but not pre-fetched text. Uses the pipeline's
        shared httpx client so connection pools are reused.

        Args:
            extraction_input: Input with source_url set but raw_content absent.

        Returns:
            A copy of the input with raw_content set to the fetched page text.

        Raises:
            RuntimeError: If the HTTP request fails or returns a non-text response.
        """
        url = extraction_input.source_url
        logger.info(
            f"Fetching document content from {url}",
            extra={"operation": "pipeline_fetch_document", "url": url},
        )
        try:
            response = await self._http_client.get(url, headers=_FETCH_HEADERS)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

        if _is_pdf(response):
            logger.info(
                f"_fetch_and_populate: PDF detected at {url} — extracting text with pypdf",
                extra={"operation": "pipeline_pdf_fetch", "url": url},
            )
            raw_text = _extract_pdf_text(response.content)[:_MAX_PDF_CHARS]
        else:
            raw_text = _html_to_text(response.text)[:_MAX_FETCH_CHARS]
            if len(raw_text) < _SPA_THRESHOLD:
                logger.info(
                    f"_fetch_and_populate: thin content ({len(raw_text)} chars) at {url} "
                    "— switching to Playwright",
                    extra={"operation": "pipeline_playwright_fallback", "url": url},
                )
                try:
                    pages = await _fetch_pages_playwright(url, response.text, max_subpages=0)
                    raw_text = pages[0][1] if pages else raw_text
                except Exception as exc:
                    logger.warning(
                        f"_fetch_and_populate: Playwright failed ({exc}) — using "
                        f"static httpx content ({len(raw_text)} chars)",
                        extra={"operation": "pipeline_playwright_failed", "url": url},
                    )

        logger.info(
            f"Fetched {len(raw_text)} chars from {url}",
            extra={"operation": "pipeline_fetch_complete", "url": url, "chars": len(raw_text)},
        )

        return ExtractionInput(
            trace_id=extraction_input.trace_id,
            company_id=extraction_input.company_id,
            source_url=url,
            source_type=extraction_input.source_type,
            raw_content=raw_text,
            publication_date=extraction_input.publication_date,
        )

    # ---------------------------------------------------------------------------
    # Persistence helpers
    # ---------------------------------------------------------------------------

    async def _persist_trace(self, trace: AgentTrace) -> None:
        """Write an AgentTrace record to the database.

        Args:
            trace: The trace record to persist.
        """
        if not self._config.persist_traces:
            return
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO trace_log "
                        "(id, trace_id, claim_id, agent, outcome, started_at, "
                        " completed_at, duration_ms, input_schema, output_schema, "
                        " error_type, error_message, retry_count, llm_model_id, "
                        " tokens_used, metadata) "
                        "VALUES "
                        "(:id, :trace_id, :claim_id, :agent, :outcome, :started_at, "
                        " :completed_at, :duration_ms, :input_schema, :output_schema, "
                        " :error_type, :error_message, :retry_count, :llm_model_id, "
                        " :tokens_used, :metadata)"
                    ),
                    _trace_to_params(trace),
                )
        except Exception as exc:
            # Trace persistence failures are non-fatal; the pipeline continues.
            self.last_run_persist_failures += 1
            logger.warning(
                f"Failed to persist trace {trace.id}: {exc}",
                extra={"operation": "persist_trace_failed", "error_type": type(exc).__name__},
            )

    async def _persist_claim(self, claim: Claim) -> None:
        """Write a Claim record to the database.

        Args:
            claim: The claim to persist.
        """
        if not self._config.persist_claims:
            return
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO claims "
                        "(id, trace_id, company_id, source_url, source_type, "
                        " raw_text, normalised_text, claim_category, page_reference, "
                        " publication_date, detected_at, status, is_repeat, "
                        " previous_claim_id, modified_after_scoring, original_scored_text) "
                        "VALUES "
                        "(:id, :trace_id, :company_id, :source_url, :source_type, "
                        " :raw_text, :normalised_text, :claim_category, :page_reference, "
                        " :publication_date, :detected_at, :status, :is_repeat, "
                        " :previous_claim_id, :modified_after_scoring, :original_scored_text) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    _claim_to_params(claim),
                )
        except Exception as exc:
            self.last_run_persist_failures += 1
            logger.warning(
                f"Failed to persist claim {claim.id}: {exc}",
                extra={"operation": "persist_claim_failed", "error_type": type(exc).__name__},
            )

    async def _persist_evidence(self, verification: VerificationResult) -> None:
        """Write all Evidence records from a verification pass to the database.

        Every data point the Verification Agent gathered — including the full
        parsed upstream response in ``raw_data`` — is persisted so a published
        verdict can be reconstructed from exactly what the pipeline saw at run
        time. Write-once: existing rows are never updated (ON CONFLICT DO
        NOTHING), preserving the audit chain.

        Args:
            verification: The sealed verification result whose evidence to persist.
        """
        if not self._config.persist_claims or not verification.evidence:
            return
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO evidence "
                        "(id, claim_id, trace_id, source, evidence_type, source_url, "
                        " retrieved_at, raw_data, summary, data_year, supports_claim, "
                        " confidence) "
                        "VALUES "
                        "(:id, :claim_id, :trace_id, :source, :evidence_type, :source_url, "
                        " :retrieved_at, :raw_data, :summary, :data_year, :supports_claim, "
                        " :confidence) "
                        "ON CONFLICT (id) DO NOTHING"
                    ),
                    [
                        {
                            "id": str(ev.id),
                            "claim_id": str(ev.claim_id),
                            "trace_id": str(ev.trace_id),
                            "source": ev.source.value,
                            "evidence_type": ev.evidence_type.value,
                            "source_url": ev.source_url,
                            "retrieved_at": ev.retrieved_at,
                            # default=str: upstream raw_data may contain dates
                            # or Decimals that json.dumps cannot serialise.
                            "raw_data": json.dumps(ev.raw_data, default=str),
                            "summary": ev.summary,
                            "data_year": ev.data_year,
                            "supports_claim": ev.supports_claim,
                            "confidence": ev.confidence,
                        }
                        for ev in verification.evidence
                    ],
                )
        except Exception as exc:
            self.last_run_persist_failures += 1
            logger.warning(
                f"Failed to persist {len(verification.evidence)} evidence record(s): {exc}",
                extra={"operation": "persist_evidence_failed", "error_type": type(exc).__name__},
            )

    async def _persist_score(self, score: GreenwashingScore) -> None:
        """Write a GreenwashingScore record to the database.

        Args:
            score: The score to persist.
        """
        if not self._config.persist_claims:
            return
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO greenwashing_scores "
                        "(id, claim_id, company_id, trace_id, score, score_low, score_high, "
                        " score_breakdown, verdict, reasoning, confidence, evidence_ids, "
                        " scored_at, judge_model_id) "
                        "VALUES "
                        "(:id, :claim_id, :company_id, :trace_id, :score, :score_low, "
                        " :score_high, :score_breakdown, :verdict, :reasoning, :confidence, "
                        " :evidence_ids, :scored_at, :judge_model_id)"
                    ),
                    {
                        "id": str(score.id),
                        "claim_id": str(score.claim_id),
                        "company_id": str(score.company_id),
                        "trace_id": str(score.trace_id),
                        "score": score.score,
                        "score_low": score.score_low,
                        "score_high": score.score_high,
                        "score_breakdown": json.dumps(score.score_breakdown),
                        "verdict": score.verdict.value,
                        "reasoning": score.reasoning,
                        "confidence": score.confidence,
                        "evidence_ids": json.dumps([str(eid) for eid in score.evidence_ids]),
                        "scored_at": score.scored_at,
                        "judge_model_id": score.judge_model_id,
                    },
                )
        except Exception as exc:
            self.last_run_persist_failures += 1
            logger.warning(
                f"Failed to persist score {score.id}: {exc}",
                extra={"operation": "persist_score_failed", "error_type": type(exc).__name__},
            )

    async def _persist_report(self, claim: Claim, report_markdown: str) -> None:
        """Write the report Markdown to the database.

        Args:
            claim: The claim the report was produced for.
            report_markdown: The Markdown report content.
        """
        if not self._config.persist_claims:
            return
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO reports (claim_id, trace_id, report_markdown, published_at) "
                        "VALUES (:claim_id, :trace_id, :report_markdown, :published_at) "
                        "ON CONFLICT (claim_id) DO UPDATE SET "
                        "  report_markdown = EXCLUDED.report_markdown, "
                        "  published_at = EXCLUDED.published_at"
                    ),
                    {
                        "claim_id": str(claim.id),
                        "trace_id": str(claim.trace_id),
                        "report_markdown": report_markdown,
                        "published_at": datetime.now(UTC),
                    },
                )
        except Exception as exc:
            self.last_run_persist_failures += 1
            logger.warning(
                f"Failed to persist report for claim {claim.id}: {exc}",
                extra={"operation": "persist_report_failed", "error_type": type(exc).__name__},
            )

    async def _transition_claim_status(
        self,
        claim: Claim,
        to_status: ClaimStatus,
        transitioned_by: str,
    ) -> None:
        """Record a claim lifecycle status transition in the database.

        Args:
            claim: The claim whose status is changing.
            to_status: The new status.
            transitioned_by: Agent name that triggered the transition.
        """
        if not self._config.persist_claims:
            return
        lifecycle = ClaimLifecycle(
            claim_id=claim.id,
            from_status=claim.status,
            to_status=to_status,
            transitioned_by=transitioned_by,
        )
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO claim_lifecycle "
                        "(id, claim_id, from_status, to_status, transitioned_at, transitioned_by) "
                        "VALUES (:id, :claim_id, :from_status, :to_status, :transitioned_at, :transitioned_by)"
                    ),
                    {
                        "id": str(lifecycle.id),
                        "claim_id": str(lifecycle.claim_id),
                        "from_status": lifecycle.from_status.value
                        if lifecycle.from_status
                        else None,
                        "to_status": lifecycle.to_status.value,
                        "transitioned_at": lifecycle.transitioned_at,
                        "transitioned_by": lifecycle.transitioned_by,
                    },
                )
                await session.execute(
                    text("UPDATE claims SET status = :status WHERE id = :claim_id"),
                    {"status": to_status.value, "claim_id": str(claim.id)},
                )
        except Exception as exc:
            self.last_run_persist_failures += 1
            logger.warning(
                f"Failed to transition claim {claim.id} to {to_status}: {exc}",
                extra={"operation": "transition_claim_failed", "error_type": type(exc).__name__},
            )


# ---------------------------------------------------------------------------
# Parameter helpers
# ---------------------------------------------------------------------------


def _trace_to_params(trace: AgentTrace) -> dict[str, Any]:
    """Serialise an AgentTrace to a SQL parameter dict.

    Args:
        trace: The trace to serialise.

    Returns:
        Dict suitable for use as SQLAlchemy text() bind parameters.
    """
    return {
        "id": str(trace.id),
        "trace_id": str(trace.trace_id),
        "claim_id": str(trace.claim_id) if trace.claim_id else None,
        "agent": trace.agent.value,
        "outcome": trace.outcome.value,
        "started_at": trace.started_at,
        "completed_at": trace.completed_at,
        "duration_ms": trace.duration_ms,
        "input_schema": trace.input_schema,
        "output_schema": trace.output_schema,
        "error_type": trace.error_type,
        "error_message": trace.error_message,
        "retry_count": trace.retry_count,
        "llm_model_id": trace.llm_model_id,
        "tokens_used": trace.tokens_used,
        "metadata": json.dumps(trace.metadata),
    }


def _claim_to_params(claim: Claim) -> dict[str, Any]:
    """Serialise a Claim to a SQL parameter dict.

    Args:
        claim: The claim to serialise.

    Returns:
        Dict suitable for use as SQLAlchemy text() bind parameters.
    """
    return {
        "id": str(claim.id),
        "trace_id": str(claim.trace_id),
        "company_id": str(claim.company_id),
        "source_url": claim.source_url,
        "source_type": claim.source_type.value,
        "raw_text": claim.raw_text,
        "normalised_text": claim.normalised_text,
        "claim_category": claim.claim_category.value,
        "page_reference": claim.page_reference,
        "publication_date": claim.publication_date,
        "detected_at": claim.detected_at,
        "status": claim.status.value,
        "is_repeat": claim.is_repeat,
        "previous_claim_id": str(claim.previous_claim_id) if claim.previous_claim_id else None,
        "modified_after_scoring": claim.modified_after_scoring,
        "original_scored_text": claim.original_scored_text,
    }

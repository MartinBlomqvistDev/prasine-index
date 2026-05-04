"""Top-level pipeline orchestrator for the Prasine Index system.

Wires all seven agents into the complete claim verification workflow and handles
the database persistence layer between agent steps. Each agent step is isolated:
the orchestrator commits its trace and any produced models to PostgreSQL before
invoking the next agent, so that a failure at any stage leaves a complete audit
trail of everything that succeeded.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

import anthropic
import httpx
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
from models.claim import Claim, ClaimLifecycle, ClaimStatus, SourceType
from models.company import Company
from models.score import GreenwashingScore
from models.trace import AgentName, AgentTrace

__all__ = [
    "Pipeline",
    "PipelineConfig",
    "PipelineResult",
]

# ---------------------------------------------------------------------------
# HTML → plain text utility (used when pipeline fetches a URL directly)
# ---------------------------------------------------------------------------

_SKIP_TAGS = frozenset(
    {"script", "style", "nav", "footer", "header", "noscript", "iframe", "aside", "form"}
)
_MAX_FETCH_CHARS = 40_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self._parts)).strip()


def _html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.get_text()


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
    re.compile(r"\d{1,3}[,\s]?\d{3}"),  # large numbers (e.g. 200,000)
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


def _claim_priority_score(claim: Claim) -> int:
    """Return a priority score for a claim — higher means more worth verifying.

    Combines category weight with text specificity heuristics so that a
    quantified CCS or net-zero claim always outranks vague responsibility copy.
    """
    category_score = _CATEGORY_WEIGHT.get(claim.claim_category.value, 1)
    text = (claim.raw_text or "") + " " + (claim.normalised_text or "")
    specificity = sum(1 for p in _SPECIFICITY_PATTERNS if p.search(text))
    return category_score + specificity


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
    judge_model: str = Field(default="claude-haiku-4-5-20251001")
    report_model: str = Field(default="claude-haiku-4-5-20251001")
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
        self._verification_agent = VerificationAgent()
        self._lobbying_agent = LobbyingAgent(http_client=self._http_client)
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
        max_subpages: int = 5,
        max_claims: int = 5,
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
        _headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; PrasineIndex/1.0; "
                "+https://github.com/MartinBlomqvistDev/prasine-index)"
            ),
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            "Accept-Language": "sv,en-GB;q=0.9,en;q=0.8",
        }

        # --- Phase 1: fetch all pages (cheap) ---
        logger.info(
            f"run_from_url: fetching {source_url}",
            extra={"operation": "pipeline_run_from_url", "url": source_url},
        )
        try:
            resp = await self._http_client.get(source_url, headers=_headers)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch {source_url}: {exc}") from exc

        raw_html = resp.text
        pages: list[tuple[str, str]] = []  # (url, extracted_text)
        entry_text = _html_to_text(raw_html)[:_MAX_FETCH_CHARS]
        if entry_text:
            pages.append((source_url, entry_text))

        seen: set[str] = {source_url.rstrip("/")}
        for sub_url in extract_relevant_links(raw_html, source_url, max_links=max_subpages):
            if sub_url in seen:
                continue
            seen.add(sub_url)
            try:
                sub_resp = await self._http_client.get(sub_url, headers=_headers)
                sub_resp.raise_for_status()
                sub_text = _html_to_text(sub_resp.text)[:_MAX_FETCH_CHARS]
                if sub_text:
                    pages.append((sub_url, sub_text))
                    logger.info(
                        f"run_from_url: discovered subpage {sub_url}",
                        extra={"operation": "pipeline_subpage_fetched", "url": sub_url},
                    )
            except Exception as exc:
                logger.warning(
                    f"run_from_url: skipping subpage {sub_url}: {exc}",
                    extra={"operation": "pipeline_subpage_failed", "url": sub_url},
                )

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

        # --- Phase 3: rank claims, keep top N ---
        ranked = sorted(all_claims, key=_claim_priority_score, reverse=True)
        selected = ranked[:max_claims]

        logger.info(
            f"run_from_url: {len(all_claims)} claims extracted, "
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

        return all_results

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
            response = await self._http_client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; PrasineIndex/1.0; "
                        "+https://github.com/MartinBlomqvistDev/prasine-index)"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type or response.content[:4] == b"%PDF":
            raise RuntimeError(
                f"{url} returned a PDF. Download it and pass the text via --claim instead."
            )

        raw_text = _html_to_text(response.text)
        if len(raw_text) > _MAX_FETCH_CHARS:
            raw_text = raw_text[:_MAX_FETCH_CHARS]

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
            logger.warning(
                f"Failed to persist claim {claim.id}: {exc}",
                extra={"operation": "persist_claim_failed", "error_type": type(exc).__name__},
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
                        "(id, claim_id, company_id, trace_id, score, score_breakdown, "
                        " verdict, reasoning, confidence, scored_at, judge_model_id) "
                        "VALUES "
                        "(:id, :claim_id, :company_id, :trace_id, :score, "
                        " :score_breakdown, :verdict, :reasoning, :confidence, "
                        " :scored_at, :judge_model_id)"
                    ),
                    {
                        "id": str(score.id),
                        "claim_id": str(score.claim_id),
                        "company_id": str(score.company_id),
                        "trace_id": str(score.trace_id),
                        "score": score.score,
                        "score_breakdown": json.dumps(score.score_breakdown),
                        "verdict": score.verdict.value,
                        "reasoning": score.reasoning,
                        "confidence": score.confidence,
                        "scored_at": score.scored_at,
                        "judge_model_id": score.judge_model_id,
                    },
                )
        except Exception as exc:
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

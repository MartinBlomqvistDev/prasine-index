"""Report Agent for the Prasine Index pipeline.

Receives the complete evidence package and the Judge Agent's verdict and generates
a publication-ready report in Markdown. Every green claim links to its
counter-evidence with full source citations. Output is designed to be reproduced
verbatim by journalists, NGOs, and used as supporting material in litigation.
Uses raw Anthropic SDK because report generation requires precise control over
tone, citation format, and the explicit accountability framing that defines the
Prasine Index brand.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from core.logger import bind_trace_context, get_logger
from core.retry import (
    LLMError,
    RetryConfig,
    agent_error_boundary,
    classify_anthropic_error,
    retry_async,
)
from models.claim import Claim
from models.company import CompanyContext
from models.evidence import VerificationResult
from models.lobbying import LobbyingRecord
from models.score import GreenwashingScore
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "ReportAgent",
    "ReportInput",
    "ReportResult",
]

logger = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are the report writer for Prasine Index, an independent EU corporate \
greenwashing accountability system. Your reports are read by investigative \
journalists at The Guardian and Le Monde, lawyers at ClientEarth, analysts \
at Greenpeace and WWF, and EU Commission officials.

REPORT STANDARDS
Your reports must meet the standard required for citation in legal proceedings:
- Every factual assertion must cite a specific evidence source.
- Claim text must be quoted verbatim — never paraphrased.
- Verdicts must be stated plainly, not hedged with "may" or "appears to".
- Data gaps must be disclosed: state what could not be verified and why.
- Tone: authoritative, precise, neutral. Not campaigning language.

STRUCTURE
Use the following Markdown structure:

## [Company Name] — Greenwashing Assessment
**Verdict: [VERDICT]** | Score: [X/100] | Confidence: [X%]
*Published: [DATE] | Prasine Index | Trace ID: [TRACE_ID]*

### The Claim
> [verbatim claim text]
*Source: [source type], [URL], [date]*

### Evidence
[For each evidence record: what the data shows, source name, data year, URL if available]

### Assessment
[Plain-language explanation of why the claim received this score. Cite evidence records
by source name. If the claim is a repeat, say so explicitly. If lobbying contradicts the
claim, make this the lead finding.]

### Key Finding
[One or two sentences. The single most important thing a journalist needs to know.
If lobbying contradiction is confirmed, lead with that.]

### Data Gaps
[List any sources that could not be queried or returned insufficient data.
Be specific about what this means for the confidence level.]

### Methodology Note
[One paragraph explaining how Prasine Index scored this claim — which sources were
used, what the score scale means, and where the full methodology is published.
Always end with: "Full Prasine Index methodology: https://martinblomqvistdev.github.io/prasine-index/"]

CITATION FORMAT
When citing evidence: [Source Name], [data year], [URL if available].
Example: EU ETS EUTL verified data, 2023, https://ec.europa.eu/clima/ets
\
"""


class ReportInput(BaseModel):
    """Input contract for the Report Agent.

    Contains the complete assessment package: claim, company context,
    verification evidence, lobbying record, and the judge's verdict.

    Attributes:
        claim: The assessed claim.
        context: Company historical context.
        verification: Verification evidence.
        lobbying: Lobbying record, or None if unavailable.
        score: The Judge Agent's greenwashing verdict.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(..., description="The assessed claim.")
    context: CompanyContext = Field(..., description="Company historical context.")
    verification: VerificationResult = Field(..., description="Aggregated verification evidence.")
    lobbying: LobbyingRecord | None = Field(default=None, description="Lobbying record or None.")
    score: GreenwashingScore = Field(..., description="The Judge Agent's greenwashing verdict.")


class ReportResult(BaseModel):
    """Output contract of the Report Agent.

    Attributes:
        report_markdown: The full publication-ready report in Markdown.
        report_plain_text: Plain text version with citations stripped to
            inline references, suitable for inclusion in legal exhibits.
        trace: Structured execution record for this agent step.
    """

    model_config = ConfigDict(from_attributes=True)

    report_markdown: str = Field(
        ...,
        description="Full publication-ready report in Markdown with inline citations.",
    )
    report_plain_text: str = Field(
        ...,
        description="Plain text version for legal exhibit use.",
    )
    trace: AgentTrace = Field(..., description="Structured execution record for this agent step.")


class ReportAgent:
    """Generates a publication-ready greenwashing assessment report.

    Receives the complete evidence package and the Judge Agent's verdict and
    uses the Anthropic SDK to produce a structured Markdown report. The report
    is designed to be reproduced verbatim: every claim is quoted verbatim,
    every evidence assertion is cited to its source, and data gaps are
    explicitly disclosed.

    Raw Anthropic SDK is used — not LangGraph — because the report is a
    single-step structured generation task where tone, citation format, and
    accountability framing require precise prompt control. The model's full
    output is the report; there is no post-processing or tool-use parsing step.

    Attributes:
        _client: Async Anthropic client.
        _model_id: Model identifier for report generation calls.
        _max_tokens: Maximum tokens for the report response.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model_id: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 4096,
    ) -> None:
        """Initialise the Report Agent.

        Args:
            client: Configured async Anthropic client.
            model_id: Model identifier. Defaults to ``claude-haiku-4-5-20251001``.
            max_tokens: Maximum tokens for the generated report.
        """
        self._client = client
        self._model_id = model_id
        self._max_tokens = max_tokens

    async def run(self, input: ReportInput) -> ReportResult:
        """Generate the publication-ready report for the given assessment.

        Args:
            input: The complete assessment package.

        Returns:
            A :py:class:`ReportResult` containing the report in Markdown and
            plain text formats, and the execution trace.

        Raises:
            :py:class:`~core.retry.LLMError`: If the API call fails after retries.
        """
        bind_trace_context(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent_name=AgentName.REPORT.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Report generation started",
            extra={
                "operation": "report_start",
                "verdict": input.score.verdict.value,
                "score": input.score.score,
            },
        )

        report_markdown: str = ""
        outcome = AgentOutcome.SUCCESS
        tokens_used: int | None = None

        async with agent_error_boundary(agent=AgentName.REPORT.value, operation="run"):
            report_markdown, tokens_used = await self._call_llm(input)

            logger.info(
                f"Report generated ({len(report_markdown)} chars)",
                extra={
                    "operation": "report_complete",
                    "tokens_used": tokens_used,
                },
            )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent=AgentName.REPORT,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.report_agent.ReportInput",
            output_schema="agents.report_agent.ReportResult",
            llm_model_id=self._model_id,
            tokens_used=tokens_used,
            metadata={
                "report_chars": len(report_markdown),
                "verdict": input.score.verdict.value,
            },
        )

        return ReportResult(
            report_markdown=report_markdown,
            report_plain_text=_markdown_to_plain(report_markdown),
            trace=trace,
        )

    @retry_async(config=RetryConfig.DEFAULT_LLM, operation="report_llm_call")
    async def _call_llm(self, input: ReportInput) -> tuple[str, int]:
        """Call the Anthropic API to generate the report text.

        Args:
            input: The complete assessment package.

        Returns:
            A tuple of (report_markdown_string, tokens_used).

        Raises:
            :py:class:`~core.retry.LLMError`: On API failure.
        """
        user_message = _build_report_prompt(input)

        try:
            response = await self._client.messages.create(
                model=self._model_id,
                max_tokens=self._max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": _SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIStatusError as exc:
            raise classify_anthropic_error(
                exc,
                agent=AgentName.REPORT.value,
                llm_model_id=self._model_id,
            ) from exc

        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        report_text = "".join(block.text for block in response.content if hasattr(block, "text"))

        if not report_text.strip():
            raise LLMError(
                message="Report agent received an empty response from the model.",
                agent=AgentName.REPORT.value,
                retryable=True,
                llm_model_id=self._model_id,
            )

        return report_text, tokens_used


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_report_prompt(input: ReportInput) -> str:
    """Construct the user message for the report generation call.

    Args:
        input: The complete report input.

    Returns:
        A formatted prompt string.
    """
    score = input.score
    claim = input.claim
    company = input.context.company
    vr = input.verification

    today = datetime.now(UTC).date().isoformat()

    parts: list[str] = [
        "Please generate a Prasine Index assessment report for the following case.",
        "",
        f"DATE: {today}",
        f"TRACE ID: {claim.trace_id}",
        "",
        f"COMPANY: {company.name} | {company.country} | {company.sector}",
        f"CLAIM SOURCE: {claim.source_type.value} — {claim.source_url}",
        f'CLAIM TEXT: "{claim.raw_text}"',
        "",
        f"VERDICT: {score.verdict.value}",
        f"SCORE: {score.score:.1f}/100",
        f"CONFIDENCE: {score.confidence * 100:.0f}%",
        "",
        "JUDGE REASONING:",
        score.reasoning,
        "",
        "SCORE BREAKDOWN:",
    ]

    for dim, dim_score in score.score_breakdown.items():
        parts.append(f"  {dim}: {dim_score:.1f}/100")

    parts += ["", "EVIDENCE RECORDS:"]
    for i, ev in enumerate(vr.evidence, 1):
        parts.append(
            f"[{i}] {ev.source.value} | {ev.evidence_type.value} | Year: {ev.data_year or 'N/A'} | "
            f"Supports claim: {ev.supports_claim} | Confidence: {ev.confidence:.2f}"
        )
        parts.append(f"    {ev.summary}")
        if ev.source_url:
            parts.append(f"    URL: {ev.source_url}")

    if vr.data_gaps:
        parts += ["", "DATA GAPS:"]
        for gap in vr.data_gaps:
            parts.append(f"  - {gap}")

    if input.lobbying:
        lb = input.lobbying
        parts += [
            "",
            "LOBBYING RECORD:",
            f"  Stance: {lb.stance.value}",
            f"  Contradicts claim: {'YES' if lb.contradicts_claim else 'No'}",
        ]
        if lb.contradiction_explanation:
            parts.append(f"  Detail: {lb.contradiction_explanation}")

    if input.context.total_claims_assessed > 0:
        parts += [
            "",
            "COMPANY HISTORY:",
            f"  Prior claims assessed: {input.context.total_claims_assessed}",
            f"  Repeat claims:         {input.context.repeat_claim_count}",
            f"  Score trend:           {input.context.score_trend.value}",
            f"  This claim is a repeat: {'YES' if claim.is_repeat else 'No'}",
        ]

    return "\n".join(parts)


def _markdown_to_plain(markdown: str) -> str:
    """Convert Markdown report to plain text for legal exhibit use.

    Removes Markdown formatting characters while preserving the content
    and structure. Intended for inclusion in legal documents where
    formatting markup should not appear.

    Args:
        markdown: The Markdown-formatted report string.

    Returns:
        A plain text version of the report.
    """
    import re

    text = re.sub(r"#{1,6}\s+", "", markdown)  # headings
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)  # italic
    text = re.sub(r"`(.+?)`", r"\1", text)  # inline code
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.MULTILINE)  # bullets
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # links
    text = re.sub(r"\n{3,}", "\n\n", text)  # excess blank lines
    return text.strip()

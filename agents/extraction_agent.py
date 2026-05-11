"""Claim Extraction Agent for the Prasine Index pipeline.

Receives a raw company document — press release, CSRD report, IR page, or annual
report — and uses the Anthropic SDK with forced tool use to extract every green
claim as a structured Claim object. Uses raw Anthropic SDK (not LangGraph) because
extraction is a single-step structured output task where full prompt control and
deterministic output parsing matter more than orchestration framework features.
"""

from __future__ import annotations

import html as html_module
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

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
from models.claim import (
    Claim,
    ClaimCategory,
    ClaimStatus,
    SourceType,
)
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "ExtractionAgent",
    "ExtractionInput",
    "ExtractionResult",
]

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Tool definition — forced on every call via tool_choice
# ---------------------------------------------------------------------------

_EXTRACT_TOOL_NAME = "extract_green_claims"

_EXTRACT_TOOL: anthropic.types.ToolParam = {
    "name": _EXTRACT_TOOL_NAME,
    "description": (
        "Extract every green or sustainability-related claim from the document. "
        "Call this tool exactly once with the complete list of all claims found. "
        "If the document contains no green claims, call the tool with an empty list."
    ),
    "cache_control": {"type": "ephemeral"},
    "input_schema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "description": "Complete list of all green claims identified in the document.",
                "items": {
                    "type": "object",
                    "properties": {
                        "raw_text": {
                            "type": "string",
                            "description": (
                                "Verbatim claim text exactly as it appears in the document. "
                                "Do not paraphrase, summarise, or correct the original wording."
                            ),
                        },
                        "claim_category": {
                            "type": "string",
                            "enum": [c.value for c in ClaimCategory],
                            "description": (
                                "Most specific EU environmental claim taxonomy category that applies. "
                                "Use OTHER only if no specific category fits."
                            ),
                        },
                        "page_reference": {
                            "type": "string",
                            "description": (
                                "Page number, section title, or heading from the document that "
                                "identifies where this claim appears. Omit if not determinable."
                            ),
                        },
                    },
                    "required": ["raw_text", "claim_category"],
                },
            },
        },
        "required": ["claims"],
    },
}

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert analyst specialising in EU corporate sustainability reporting, \
EU environmental claims law (EmpCo Directive 2024/825, UCPD, CSRD), and greenwashing enforcement.

Your task is to identify and extract every green or sustainability-related claim \
present in the provided document. You work for Prasine Index, an independent \
accountability system that cross-references company claims against verified EU \
emissions data and lobbying records. Accuracy and completeness are critical: \
missed claims are missed accountability opportunities.

WHAT CONSTITUTES A GREEN CLAIM
A green claim is any assertion, commitment, target, or statement by the company \
about its environmental performance, climate ambitions, or sustainability practices. \
This includes:
- Emissions targets and net-zero commitments ("we will reach net zero by 2040")
- Present-state environmental claims ("our packaging is 100% recyclable")
- Science-based targets and certifications ("our targets are validated by SBTi")
- Renewable energy and energy efficiency claims
- Supply chain and biodiversity commitments
- Circular economy and waste reduction claims
- Carbon neutrality or climate-positive claims
- Project-specific commitments with quantified targets and timelines — THESE ARE \
  THE HIGHEST PRIORITY. A statement like "from 2029 we will capture 200,000 tonnes \
  of CO2 per year" or "Med start 2029 ska vi fånga in 200 000 ton koldioxid varje år" \
  is a specific, verifiable future commitment and must always be extracted. Extract \
  the full passage including the project name, quantity, year, and any funding context.
- Claims made in any EU language — extract verbatim in the original language without \
  translation.

WHAT TO EXCLUDE
- Purely historical emissions data in tabular form (e.g. an annual report table showing \
  "Scope 1 emissions 2023: 450,000 tCO2e") without any attached forward-looking claim.
- Legal boilerplate and regulatory compliance statements that make no environmental assertion.
- Product safety or quality claims unrelated to environmental performance.
- NOTE: A future-oriented figure with a year target is NEVER a raw disclosure — it is \
  always a claim. "We will capture X tonnes by YYYY" must be extracted even if it sounds \
  like a factual project description.

EXTRACTION RULES
1. Extract verbatim — preserve the exact wording from the document including any \
   exaggerations, vague language, or unsubstantiated assertions. The Verification \
   Agent will assess credibility; your role is accurate extraction.
2. If a claim spans multiple sentences, include the full passage needed to understand \
   the assertion in context. For project claims, include the project name, the \
   quantified target, the timeline, and any stated funding or certification.
3. Assign the most specific ClaimCategory that applies.
4. Record the page number or section heading if it is identifiable in the text.
5. Prioritise specificity: extract the most concrete, quantified claims first. A \
   vague heading like "our journey to net zero" and a specific claim like "we will \
   capture 200,000 tonnes per year from 2029" are both claims — but the specific one \
   is more important and must not be omitted in favour of the heading.
6. Call the extract_green_claims tool exactly once with the complete list.\
"""

# ---------------------------------------------------------------------------
# Hallucination firewall
# ---------------------------------------------------------------------------

_MIN_TOKEN_OVERLAP: float = 0.60
_MIN_TOKEN_LENGTH: int = 3


def _strip_html(text: str) -> str:
    text = html_module.unescape(text)
    return re.sub(r"<[^>]+>", " ", text)


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _claim_in_source(claim_text: str, source_text: str) -> bool:
    """Return True if enough of the claim's tokens appear in the source."""
    norm_source = _normalize(_strip_html(source_text))
    tokens = [t for t in _normalize(claim_text).split() if len(t) >= _MIN_TOKEN_LENGTH]
    if not tokens:
        return True
    matched = sum(1 for t in tokens if t in norm_source)
    return matched / len(tokens) >= _MIN_TOKEN_OVERLAP


# ---------------------------------------------------------------------------
# I/O models
# ---------------------------------------------------------------------------


class ExtractionInput(BaseModel):
    """Input contract for the Claim Extraction Agent.

    Produced by the Discovery Agent and passed directly to
    :py:class:`ExtractionAgent.run`. Contains the raw document content and
    all metadata needed to construct :py:class:`~models.claim.Claim` objects
    without additional lookups.

    Attributes:
        trace_id: Pipeline-wide trace identifier assigned by the Discovery
            Agent. Shared across all subsequent agent steps for this document.
        company_id: The company that published this document.
        source_url: Canonical URL of the document.
        source_type: Document category (CSRD report, press release, etc.).
        raw_content: Full text content of the document as extracted by the
            Discovery Agent. No length limit is imposed here; the
            :py:class:`ExtractionAgent` is responsible for handling documents
            that approach model context limits.
        publication_date: Publication date of the document, if determinable
            by the Discovery Agent.
    """

    model_config = ConfigDict(from_attributes=True)

    trace_id: uuid.UUID = Field(
        ..., description="Pipeline trace identifier assigned by the Discovery Agent."
    )
    company_id: uuid.UUID = Field(..., description="Company that published this document.")
    source_url: str = Field(..., description="Canonical URL of the source document.")
    source_type: SourceType = Field(..., description="Document category.")
    raw_content: str | None = Field(
        default=None,
        description=(
            "Full extracted text content of the document. "
            "If None, the pipeline fetches and extracts text from source_url automatically."
        ),
    )
    publication_date: datetime | None = Field(
        default=None,
        description="Publication date of the document, if determinable.",
    )


class ExtractionResult(BaseModel):
    """Output contract of the Claim Extraction Agent.

    Returned by :py:meth:`ExtractionAgent.run` and passed to the Context Agent.
    Bundles the extracted claims with the agent's execution trace so the pipeline
    orchestrator can persist both in a single database transaction.

    Attributes:
        claims: All green claims extracted from the document. Empty list if the
            document contained no green claims.
        trace: Structured execution record for this agent step. Persisted by
            the pipeline orchestrator to the ``trace_log`` table.
    """

    model_config = ConfigDict(from_attributes=True)

    claims: list[Claim] = Field(
        default_factory=list,
        description="All green claims extracted from the document.",
    )
    trace: AgentTrace = Field(..., description="Structured execution record for this agent step.")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class ExtractionAgent:
    """Extracts structured green claims from raw company documents.

    Uses the Anthropic SDK with forced tool use to identify every green or
    sustainability-related claim in a document and return each as a fully
    constructed :py:class:`~models.claim.Claim` instance.

    This agent uses the raw Anthropic SDK rather than LangGraph because claim
    extraction is a single-step, single-tool task. There is no branching logic,
    no multi-tool orchestration, and no state machine — a framework would add
    indirection without adding value. Full control over the prompt and response
    parsing produces cleaner, more auditable code.

    Attributes:
        _client: Async Anthropic client.
        _model_id: Anthropic model identifier to use for extraction calls.
        _max_tokens: Maximum tokens to request in the model response.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model_id: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 4096,
    ) -> None:
        """Initialise the Extraction Agent.

        Args:
            client: Configured async Anthropic client. The caller is responsible
                for lifecycle management (the client is not closed by this agent).
            model_id: Anthropic model identifier. Defaults to ``claude-haiku-4-5-20251001``
                for cost-efficient extraction. Use ``claude-opus-4-6``
                in development to reduce latency and cost.
            max_tokens: Maximum tokens to request in the completion. The default
                of 4096 accommodates documents with a large number of claims.
                Increase for unusually claim-dense CSRD reports.
        """
        self._client = client
        self._model_id = model_id
        self._max_tokens = max_tokens

    async def run(self, input: ExtractionInput) -> ExtractionResult:
        """Extract all green claims from the provided document.

        Entry point for the Extraction Agent. Binds the pipeline context
        variables so all log records produced during extraction carry the
        correct ``trace_id`` and ``agent`` fields. Creates and returns an
        :py:class:`ExtractionResult` containing the extracted claims and the
        execution trace record.

        If the document contains no green claims, returns an
        :py:class:`ExtractionResult` with an empty ``claims`` list and
        ``AgentOutcome.SUCCESS`` — the absence of claims is a valid and
        expected outcome for some documents.

        Args:
            input: Validated extraction input produced by the Discovery Agent.

        Returns:
            An :py:class:`ExtractionResult` with all extracted claims and the
            execution trace. The pipeline orchestrator persists both.

        Raises:
            :py:class:`~core.retry.LLMError`: If the Anthropic API call fails
                after all retry attempts are exhausted.
            :py:class:`~core.retry.ExtractionError`: If the model response
                cannot be parsed into valid :py:class:`~models.claim.Claim`
                objects.
        """
        if not input.raw_content:
            raise ValueError(
                "ExtractionInput.raw_content is empty. "
                "The pipeline should fetch the URL before calling ExtractionAgent."
            )

        bind_trace_context(
            trace_id=input.trace_id,
            agent_name=AgentName.EXTRACTION.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Extraction started",
            extra={
                "operation": "extraction_start",
                "company_id": str(input.company_id),
            },
        )

        claims: list[Claim] = []
        outcome = AgentOutcome.SUCCESS
        tokens_used: int | None = None
        error_type: str | None = None
        error_message: str | None = None

        async with agent_error_boundary(agent=AgentName.EXTRACTION.value, operation="run"):
            raw_claims, tokens_used = await self._call_llm(input.raw_content)
            claims = self._build_claims(raw_claims, input)

            verified: list[Claim] = []
            for claim in claims:
                if _claim_in_source(claim.raw_text, input.raw_content):
                    verified.append(claim)
                else:
                    logger.warning(
                        "claim_not_found_in_source",
                        extra={
                            "operation": "claim_not_found_in_source",
                            "source_url": input.source_url,
                            "claim_text": claim.raw_text[:120],
                        },
                    )
            claims = verified

            if not claims:
                outcome = AgentOutcome.PARTIAL
                logger.info(
                    "Extraction completed with no claims found",
                    extra={
                        "operation": "extraction_complete",
                        "outcome": outcome.value,
                        "tokens_used": tokens_used,
                    },
                )
            else:
                logger.info(
                    f"Extraction completed: {len(claims)} claim(s) extracted",
                    extra={
                        "operation": "extraction_complete",
                        "outcome": outcome.value,
                        "tokens_used": tokens_used,
                    },
                )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.trace_id,
            claim_id=None,
            agent=AgentName.EXTRACTION,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.extraction_agent.ExtractionInput",
            output_schema="agents.extraction_agent.ExtractionResult",
            error_type=error_type,
            error_message=error_message,
            llm_model_id=self._model_id,
            tokens_used=tokens_used,
            metadata={
                "claims_extracted": len(claims),
                "source_url": input.source_url,
                "source_type": input.source_type.value,
            },
        )

        return ExtractionResult(claims=claims, trace=trace)

    @retry_async(config=RetryConfig.DEFAULT_LLM, operation="extraction_llm_call")
    async def _call_llm(self, document: str) -> tuple[list[dict[str, Any]], int]:
        """Call the Anthropic API with forced tool use to extract claims.

        Forces the model to call the ``extract_green_claims`` tool exactly once
        by setting ``tool_choice`` to the specific tool name. This guarantees
        that the response is always a tool use block — there is no fallback text
        path to handle. The tool input contains the structured claims list.

        Args:
            document: Full text content of the document to analyse.

        Returns:
            A tuple of:
            - ``list[dict]``: The raw claim dicts from the tool call input,
              each containing ``raw_text``, ``claim_category``, and optionally
              ``page_reference``.
            - ``int``: Total tokens used by the API call (input + output).

        Raises:
            :py:class:`~core.retry.LLMError`: If the API call fails or the
                response does not contain the expected tool use block.
        """
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
                tools=[_EXTRACT_TOOL],
                tool_choice=anthropic.types.ToolChoiceToolParam(
                    type="tool", name=_EXTRACT_TOOL_NAME
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Please extract all green claims from the following document.\n\n"
                            f"{document}"
                        ),
                    }
                ],
            )
        except anthropic.APIStatusError as exc:
            raise classify_anthropic_error(
                exc,
                agent=AgentName.EXTRACTION.value,
                llm_model_id=self._model_id,
            ) from exc

        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        tool_block = next(
            (block for block in response.content if block.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise LLMError(
                message=(
                    f"Anthropic response for model {self._model_id} contained no tool use block. "
                    f"Stop reason: {response.stop_reason!r}. "
                    "This indicates a prompt or model behaviour change and requires investigation."
                ),
                agent=AgentName.EXTRACTION.value,
                retryable=False,
                llm_model_id=self._model_id,
            )

        raw_claims: list[dict[str, Any]] = cast("dict[str, Any]", tool_block.input).get(
            "claims", []
        )

        logger.info(
            f"LLM call completed: {len(raw_claims)} raw claim(s) returned",
            extra={
                "operation": "extraction_llm_call",
                "tokens_used": tokens_used,
                "llm_model_id": self._model_id,
            },
        )

        return raw_claims, tokens_used

    def _build_claims(
        self,
        raw_claims: list[dict[str, Any]],
        input: ExtractionInput,
    ) -> list[Claim]:
        """Construct validated Claim objects from raw LLM tool output.

        Iterates over the raw claim dicts returned by the tool call and builds
        a :py:class:`~models.claim.Claim` for each. Claims that fail Pydantic
        validation are logged and skipped rather than failing the entire
        extraction run — partial results are better than no results.

        The ``trace_id`` is shared across all claims extracted from a single
        document, linking them to the same pipeline trace. Each claim receives
        its own ``id`` UUID. The ``normalised_text`` is derived from
        ``raw_text`` in code rather than delegating that transformation to the
        LLM.

        Args:
            raw_claims: List of raw claim dicts from the LLM tool call.
            input: The original extraction input providing document metadata.

        Returns:
            List of validated :py:class:`~models.claim.Claim` objects.
        """
        claims: list[Claim] = []

        for idx, raw in enumerate(raw_claims):
            raw_text: str = raw.get("raw_text", "").strip()
            if not raw_text:
                logger.warning(
                    f"Skipping claim at index {idx}: raw_text is empty",
                    extra={"operation": "claim_build_skipped"},
                )
                continue

            try:
                claim = Claim(
                    trace_id=input.trace_id,
                    company_id=input.company_id,
                    source_url=input.source_url,
                    source_type=input.source_type,
                    raw_text=raw_text,
                    normalised_text=_normalise_text(raw_text),
                    claim_category=ClaimCategory(
                        raw.get("claim_category", ClaimCategory.OTHER.value)
                    ),
                    page_reference=raw.get("page_reference") or None,
                    publication_date=input.publication_date,
                    status=ClaimStatus.DETECTED,
                )
                claims.append(claim)

            except Exception as exc:
                logger.warning(
                    f"Skipping claim at index {idx}: validation failed — {exc}",
                    extra={
                        "operation": "claim_build_failed",
                        "error_type": type(exc).__name__,
                    },
                )

        return claims


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_text(text: str) -> str:
    """Produce a normalised version of claim text for pgvector similarity search.

    Applies case folding, whitespace normalisation, and removal of punctuation
    that does not carry semantic meaning for embedding similarity purposes.
    The result is stored in :py:attr:`~models.claim.Claim.normalised_text` and
    used as the input to the pgvector embedding column.

    Args:
        text: The raw claim text to normalise.

    Returns:
        A normalised, lower-cased string suitable for embedding generation.
    """
    # Case-fold and collapse internal whitespace
    normalised = " ".join(text.lower().split())
    # Remove characters that add no semantic value for vector similarity
    normalised = re.sub(r"[\"'" "'']+", "", normalised)
    normalised = re.sub(r"\s+", " ", normalised).strip()
    return normalised

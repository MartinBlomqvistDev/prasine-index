"""Judge Agent for the Prasine Index pipeline.

Receives the full evidence package — extracted claim, company context,
verification results, and lobbying record — and uses the Anthropic SDK with
forced tool use to produce a calibrated GreenwashingScore with chain-of-thought
reasoning. Uses raw Anthropic SDK because the judging logic is the most sensitive
part of the pipeline: framework abstraction here would obscure what the model is
being asked to do and make prompt iteration harder to audit.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from core.logger import bind_trace_context, get_logger
from core.retry import (
    ExtractionError,
    LLMError,
    RetryConfig,
    agent_error_boundary,
    classify_anthropic_error,
    retry_async,
)
from models.claim import Claim
from models.company import CompanyContext
from models.evidence import EvidenceType, VerificationResult
from models.lobbying import LobbyingRecord
from models.score import GreenwashingScore, ScoreCategory, ScoreVerdict
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "JudgeAgent",
    "JudgeInput",
    "JudgeResult",
]

logger = get_logger(__name__)

_JUDGE_TOOL_NAME = "produce_verdict"

_JUDGE_TOOL: anthropic.types.ToolParam = {
    "name": _JUDGE_TOOL_NAME,
    "description": (
        "Produce a calibrated greenwashing verdict for the claim under assessment. "
        "Call this tool exactly once with your complete verdict after analysing all evidence."
    ),
    "cache_control": {"type": "ephemeral"},
    "input_schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 100.0,
                "description": (
                    "Overall greenwashing index from 0 to 100. "
                    "0 = claim fully substantiated by verified data. "
                    "100 = confirmed, well-evidenced greenwashing. "
                    "Be calibrated: a score above 70 requires strong contradicting evidence."
                ),
            },
            "score_breakdown": {
                "type": "object",
                "description": (
                    "Per-dimension scores keyed by ScoreCategory. "
                    "Only include dimensions for which you have sufficient evidence. "
                    "Each value must be in [0, 100]."
                ),
                "properties": {
                    cat.value: {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 100.0,
                    }
                    for cat in ScoreCategory
                },
            },
            "verdict": {
                "type": "string",
                "enum": [v.value for v in ScoreVerdict],
                "description": (
                    "Verdict band — must match your score per the bands below. "
                    "score 0–20 → SUBSTANTIATED_CLAIM. "
                    "score 21–40 → UNVERIFIABLE_CLAIM. "
                    "score 41–60 → MISLEADING_CLAIM. "
                    "score 61–80 → LIKELY_GREENWASHING. "
                    "score 81–100 → CONFIRMED_GREENWASHING."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "Full chain-of-thought reasoning for the verdict. Be specific: "
                    "cite the evidence records that drove the score, name the data "
                    "sources, and explain any data gaps. This reasoning is preserved "
                    "verbatim in the published report and may be cited in journalism "
                    "or legal proceedings. Minimum 200 words."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    "Your confidence in this verdict, from 0.0 to 1.0. "
                    "Reduce confidence when key data sources were unavailable, "
                    "evidence is conflicting, or the claim scope is ambiguous. "
                    "A score based on complete EU ETS verified data warrants "
                    "confidence >= 0.85."
                ),
            },
            "score_low": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 100.0,
                "description": (
                    "Lower bound of the plausible score range, given data uncertainty. "
                    "If all ambiguous evidence resolved in the company's favour, the score "
                    "would not fall below this value. Omit only if data is unambiguous."
                ),
            },
            "score_high": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 100.0,
                "description": (
                    "Upper bound of the plausible score range, given data uncertainty. "
                    "If all ambiguous evidence resolved against the company, the score "
                    "would not exceed this value. Omit only if data is unambiguous."
                ),
            },
            "empco_violation": {
                "type": "boolean",
                "description": (
                    "Whether this claim violates the EmpCo Directive (EU 2024/825). "
                    "Set True if the claim: (1) makes a net-zero or carbon-neutral assertion "
                    "relying on carbon offsets without certified permanent removals; or "
                    "(2) lacks any specific measurable commitment, audited baseline, or "
                    "timeline — failing the mandatory substantiation standard in amended "
                    "UCPD Annex I. Set False only when you have positively assessed that "
                    "the claim meets EmpCo substantiation requirements. Omit if the claim "
                    "type is outside EmpCo scope or if data is insufficient to assess."
                ),
            },
        },
        "required": ["score", "score_breakdown", "verdict", "reasoning", "confidence"],
    },
}

_SYSTEM_PROMPT = """\
You are a senior expert analyst at Prasine Index, an independent accountability \
system that scores EU corporate greenwashing. Your verdicts are published and \
may be cited by investigative journalists, NGOs such as Greenpeace and \
ClientEarth, and in court proceedings. Accuracy, calibration, and \
transparency of reasoning are paramount.

SCORING PHILOSOPHY
A greenwashing score measures the gap between a company's green claims and its \
verified behaviour. Score 0 means the claim is fully backed by verified data. \
Score 100 means the claim is directly and clearly contradicted by verified evidence.

SCORE-TO-VERDICT BANDS — you MUST respect these:
  0–20   → SUBSTANTIATED_CLAIM: verified data supports the claim; no material contradiction.
  21–40  → UNVERIFIABLE_CLAIM: data gaps prevent a clear assessment in either
            direction. Use ONLY when you genuinely cannot tell because the data
            needed to evaluate the claim is unavailable and the claim is at least
            plausible given the company's sector.
  41–60  → MISLEADING_CLAIM: claim is directionally possible but exaggerates, omits
            key context, or cannot be independently verified. Includes: vague
            aspirational claims without measurable targets; claims from non-emitting
            entities (banks, services) about financed or value-chain emissions that
            have no audited baseline; per-unit efficiency claims that mask rising
            absolute emissions.
  61–80  → LIKELY_GREENWASHING: claim is materially contradicted by verified data
            from a regulatory source (EU ETS EUTL), or the claim is a forward
            commitment whose current trajectory is clearly inconsistent with delivery.
  81–100 → CONFIRMED_GREENWASHING: claim is materially contradicted by verified
            data AND at least one of the following conditions is met:
            (a) LOBBYING OBSTRUCTION: the company's LobbyMap score is D or D+
                (Obstructive). A company actively obstructing the climate legislation
                required to deliver its own net-zero pledge is irreconcilably
                contradicting that pledge. D/D+ LobbyMap is sufficient — you do
                not need additional evidence of the specific legislation opposed.
            (b) CORE BUSINESS CONTRADICTION: the company's primary business
                directly and irreconcilably contradicts the claim — e.g. a coal
                producer claiming net zero while actively expanding coal mining
                and power capacity, or an oil major with multiple active FID
                extraction projects spanning decades of future production.
            (c) PRIOR REGULATORY RULING: a court or regulatory body has ruled
                the company's environmental claims misleading or greenwashing.
                The ruling does NOT need to target the exact sentence under
                assessment. A ruling against an equivalent prior claim of the
                same type (e.g. prior net-zero or emissions claim) establishes
                a documented pattern that confirms the current claim cannot be
                trusted. ASA, ACM, AGCM, DGCCRF, and EC CPC rulings all qualify.
            (d) ACCUMULATED EVIDENCE WEIGHT: three or more independent
                contradicting evidence items each with confidence ≥ 0.85, and
                no meaningful mitigating supporting evidence (no supporting
                source with confidence ≥ 0.70). When the weight of verified
                contradictions is this concentrated and uncontested, the claim
                is confirmed regardless of whether a specific ruling has been
                issued yet.

CRITICAL: Do not default to 72/LIKELY_GREENWASHING when uncertain. If you are
uncertain, use UNVERIFIABLE_CLAIM (score 21–40) or MISLEADING_CLAIM (41–60).
Reserve LIKELY_GREENWASHING (61–80) for cases where EU ETS data or other
verified evidence directly contradicts the claim.

CONFIRMED TRIGGER IS A FLOOR — CRITICAL:
When ANY ONE of conditions (a)–(d) for CONFIRMED_GREENWASHING is met, the
score CANNOT fall below 81. Mitigating evidence affects the position within the
81–100 band (e.g. strong mitigating evidence → 81–84, none → 88–95) but it
CANNOT pull the score back into the LIKELY_GREENWASHING band (≤80). A company
with a D+ LobbyMap rating and two moderate supporting sources scores 81–84, NOT 78.
Do not let partial mitigating evidence override a confirmed trigger.

INTERIM TARGETS DO NOT MITIGATE NET-ZERO CLAIMS:
SBTi "Targets set" (short-term interim reduction targets) and TPI pathway
assessments below 1.5°C do NOT mitigate a net-zero 2050 claim. They address
a different claim category. If a company has SBTi interim targets but the
claim under assessment is a net-zero commitment, SBTi is NEUTRAL — it neither
supports nor contradicts. Only SBTi net-zero validation (separately listed)
would be mitigating for a net-zero claim.

SUPPORTING EVIDENCE WEIGHT — CRITICAL
Supporting evidence ACTIVELY lowers the score. It is not merely the absence
of contradiction. When multiple independent high-confidence sources confirm
the claim, the score MUST reflect that:

  3+ independent sources with supports_claim=True (e.g. EU ETS declining
  trend + SBTi validated + CA100+ ALIGNED + LobbyMap A/B band)
  → score 5–20, verdict SUBSTANTIATED.

  2 supporting sources, no material contradiction
  → score 15–30, verdict SUBSTANTIATED or borderline INSUFFICIENT_EVIDENCE.

  1 supporting source, remaining sources show "not found" (not contradicting)
  → score 25–45, verdict INSUFFICIENT_EVIDENCE.

"Not found in database" means the source has no data — it is NEUTRAL, not
contradicting. Do NOT treat missing data as a negative signal.

RECOGNISING SUBSTANTIATED CLAIMS
Score SUBSTANTIATED (0–20) when:
- EU ETS verified emissions show a clear long-run downward trend consistent
  with the claim (e.g. an energy company that has sold fossil assets shows
  dramatically lower absolute emissions over a multi-year period).
- The company has SBTi-validated targets and its EU ETS trajectory is on track.
- The claim is a past-tense factual statement (e.g. "reduced emissions by X%
  since YEAR") and the EU ETS historical data confirms the reduction.
- CA100+ rates the company as net-zero ALIGNED with consistent capex.
- LobbyMap band is A+/A/A-/B+/B (supportive policy engagement).
When EU ETS data supports the claim, score it as SUBSTANTIATED even if
confidence is moderate. Do not inflate the score simply because other
data sources returned no record — absence of data is not contradiction.

HANDLING NON-EMITTING COMPANIES (banks, services, insurers)
These companies have no EU ETS installations. An unverifiable net-zero or
climate-neutral claim from such a company — one with no audited methodology,
no independently verified baseline, and no clear transition plan — is MISLEADING
(46–60), not INSUFFICIENT_EVIDENCE. The absence of any verification mechanism
is itself a substantiation failure under the EmpCo Directive (EU 2024/825) and UCPD Article 6.

SCORING DIMENSIONS
All dimensions are greenwashing evidence scores — higher = stronger evidence against the company.
Assess each applicable dimension independently:
- EMISSIONS_DISCREPANCY: Gap between verified emissions and what the claim implies. \
  EU ETS data is ground truth. High score = large, documented gap between reality \
  and claim. Low score = emissions data supports or is consistent with the claim.
- SUBSTANTIATION_FAILURE: Degree to which the claim lacks specific, measurable \
  commitments, audited baselines, or timelines. High score = vague aspiration with \
  no verifiable content. Low score = specific quantified targets with independent \
  verification.
- PRIOR_VIOLATIONS: Strength of documented pattern of prior misleading or \
  unsubstantiated environmental claims. High score = confirmed prior rulings or \
  repeat claims without delivery. Low score = no prior enforcement record.
- LOBBYING_CONTRADICTION: Degree to which the company's lobbying activity \
  contradicts its green claims. High score = active obstruction of climate \
  legislation (D/D+ LobbyMap) while making green claims. This is the strongest \
  greenwashing signal — if confirmed, push verdict to CONFIRMED_GREENWASHING.
- TARGET_CREDIBILITY_GAP: Distance between the stated target and a credible \
  1.5°C-aligned pathway. High score = target is inconsistent with science-based \
  pathways or missing key elements (baseline, interim checkpoints, removal plan). \
  Low score = target is validated and consistent with Paris alignment.

DATA GAP HANDLING
If key data sources were unavailable, state this explicitly in your reasoning. \
Data gaps reduce confidence but do not automatically raise the score — the \
absence of contradicting evidence is not the same as supporting evidence.

REPEAT CLAIM SIGNAL
If the company has made equivalent claims previously (indicated in the context), \
and the current assessment shows no material progress, this is a primary \
greenwashing signal. Weight it heavily in HISTORICAL_CONSISTENCY.

WORKED EXAMPLES — calibrate your scoring against these

EXAMPLE A: GREENWASHING (score 68, confidence 0.78)
Claim: "We are driving growth in social, economic and environmental sustainability."
Evidence:
  [1] GCEL: company listed as actively expanding coal — 15 Mtpa mining + 2.4 GW power
      capacity expansion confirmed. supports_claim=False, confidence=0.90
  [2] E-PRTR: regulated emissions reduced 75% from 31.97 Mt (2007) to 8.07 Mt (2024),
      consistent year-on-year decline. supports_claim=True, confidence=0.75
  [3] CA100+: Net Zero Ambition=Yes, partial capex alignment, partial short-term
      targets. supports_claim=True, confidence=0.80
Correct verdict: GREENWASHING, score=68, confidence=0.78
Why: GCEL is the institutional coal-screen standard used by 400+ financial institutions.
Active coal expansion is a direct, verified, forward-looking contradiction of any
credible "environmental sustainability" claim. Two supporting sources (E-PRTR reductions,
CA100+) provide mitigation — preventing CONFIRMED_GREENWASHING — but cannot neutralise
an active coal expansion that is irreconcilable with the claim. Score logic:
  - Contradicting source (GCEL, conf=0.90) → strong push toward 80
  - Two supporting sources → pull back ~12 points → final ~68
  - Verdict: GREENWASHING not CONFIRMED because no lobbying contradiction and
    supporting evidence shows genuine historical progress.

EXAMPLE B: CONFIRMED_GREENWASHING (score 83, confidence 0.86)
Claim: "We are committed to reaching net-zero carbon emissions by 2050."
Evidence:
  [1] LobbyMap: D+ (Obstructive) — company actively opposes climate legislation.
      supports_claim=False, confidence=0.90
  [2] ENFORCEMENT (ASA, 2020): prior "lowest carbon emissions" claim ruled
      unsubstantiated. Ruling is against an equivalent prior claim of the same type.
      supports_claim=False, confidence=0.90
  [3] ENFORCEMENT (EC CPC investigation, 2024): coordinated investigation into
      this company's environmental claims, same category as claim under assessment.
      supports_claim=False, confidence=0.80
  [4] EmpCo Directive (EU 2024/825): claim discloses no baseline year, no interim
      targets, no abatement/removal split, no verified transition plan — explicitly
      blacklisted under amended UCPD Annex I. supports_claim=False, confidence=0.95
  No supporting evidence from any queried source.
Correct verdict: CONFIRMED_GREENWASHING, score=83, confidence=0.86
Why: Conditions (a), (c), and (d) are all met independently.
  (a) D+ LobbyMap = active obstruction of climate legislation → CONFIRMED trigger.
  (c) Prior ASA ruling against equivalent emissions claim → CONFIRMED trigger.
  (d) Four contradicting sources, three at confidence ≥ 0.85, zero supporting
      evidence → CONFIRMED trigger.
Any single one of these would push the verdict above 80. With all three present
and no mitigating evidence, the score reaches 83. Confidence is 0.86 (not higher)
because the EC investigation has not yet issued a binding ruling — that would
push score and confidence higher. Score does not reach 90+ because no binding
EU court ruling on this specific claim yet exists.

EXAMPLE D: MISLEADING (score 48, confidence 0.62)
Claim: "We are committed to being a responsible business and respecting human rights
across our value chain."
Evidence:
  [1] E-PRTR: regulated emissions rose 9× over three years (2020–2023).
      supports_claim=False, confidence=0.75
  [2] SBTi: no validated science-based target on file. supports_claim=False (gap),
      confidence=0.95
  [3] EmpCo Directive (EU 2024/825) / UCPD Article 6: claim provides no specific
      targets, measurable baselines, or timelines — fails the EU substantiation standard.
  [4] LobbyMap: Band B (supportive, no contradiction). supports_claim=True,
      confidence=0.70
Correct verdict: MISLEADING, score=48, confidence=0.62
Why: The claim is aspirational with zero quantified targets, no audited baseline, and
no independent certification. The E-PRTR upward trend and SBTi absence are
contradicting signals, but the claim is so vague it cannot be fully falsified —
it exaggerates through omission, not through a specific false assertion. GREENWASHING
(61+) would require a specific factual claim directly contradicted by verified data
(e.g. "we are net-zero" + EU ETS data showing positive emissions). Here the problem
is substantiation failure: the claim has no measurable commitments, not that a
specific commitment is demonstrably broken.\
"""


class JudgeInput(BaseModel):
    """Input contract for the Judge Agent.

    Contains the complete evidence package for a single claim: the claim
    itself, the company's historical context, all verification evidence, and
    the lobbying record. The Judge Agent receives everything needed to produce
    a verdict without additional database queries.

    Attributes:
        claim: The claim being judged.
        context: Company historical context from the Context Agent.
        verification: Aggregated verification evidence from the Verification Agent.
        lobbying: Lobbying record from the Lobbying Agent, or None if unavailable.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(..., description="The claim being judged.")
    context: CompanyContext = Field(..., description="Company historical context.")
    verification: VerificationResult = Field(..., description="Aggregated verification evidence.")
    lobbying: LobbyingRecord | None = Field(
        default=None,
        description="Lobbying record, or None if the company is not in the Transparency Register.",
    )


class JudgeResult(BaseModel):
    """Output contract of the Judge Agent.

    Attributes:
        score: The calibrated greenwashing verdict.
        trace: Structured execution record for this agent step.
    """

    model_config = ConfigDict(from_attributes=True)

    score: GreenwashingScore = Field(..., description="The calibrated greenwashing verdict.")
    trace: AgentTrace = Field(..., description="Structured execution record for this agent step.")


class JudgeAgent:
    """Produces a calibrated greenwashing verdict using LLM-as-judge.

    Receives the full evidence package and uses the Anthropic SDK with forced
    tool use to produce a :py:class:`~models.score.GreenwashingScore`. The
    LLM is instructed to reason through each scoring dimension explicitly before
    producing a final score, ensuring the chain-of-thought is preserved verbatim
    in the output for audit and citation.

    Raw Anthropic SDK is used here — not LangGraph — because the judging logic
    is the most legally sensitive step in the pipeline. Every token the model
    produces is either part of the chain-of-thought reasoning (preserved in the
    ``reasoning`` field) or part of the structured verdict. Framework abstraction
    at this step would make it harder to audit, iterate on, and explain to a
    legal audience what exactly the model was asked to do.

    Attributes:
        _client: Async Anthropic client.
        _model_id: Model identifier for judging calls.
        _max_tokens: Maximum tokens for the judge response.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic,
        model_id: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 8192,
    ) -> None:
        """Initialise the Judge Agent.

        Args:
            client: Configured async Anthropic client.
            model_id: Model identifier. Defaults to ``claude-haiku-4-5-20251001``
                for cost-efficient development. Switch to ``claude-opus-4-6`` for
                production — the judge produces legally citable output and Opus
                reasoning quality matters for calibration.
            max_tokens: Maximum tokens. 8192 accommodates verbose chain-of-thought
                reasoning for complex multi-source verdicts.
        """
        self._client = client
        self._model_id = model_id
        self._max_tokens = max_tokens

    async def run(self, input: JudgeInput) -> JudgeResult:
        """Produce a greenwashing verdict for the given claim.

        Args:
            input: The complete evidence package for the claim.

        Returns:
            A :py:class:`JudgeResult` with the verdict and execution trace.

        Raises:
            :py:class:`~core.retry.LLMError`: If the Anthropic API call fails.
            :py:class:`~core.retry.ExtractionError`: If the tool response
                cannot be parsed into a valid :py:class:`~models.score.GreenwashingScore`.
        """
        bind_trace_context(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent_name=AgentName.JUDGE.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Judge run started",
            extra={
                "operation": "judge_start",
                "company_id": str(input.context.company.id),
            },
        )

        score: GreenwashingScore | None = None
        outcome = AgentOutcome.SUCCESS
        tokens_used: int | None = None

        async with agent_error_boundary(agent=AgentName.JUDGE.value, operation="run"):
            verdict_dict, tokens_used = await self._call_llm(input)
            score = self._build_score(verdict_dict, input)

            logger.info(
                f"Judge verdict: {score.verdict.value} (score={score.score:.1f}, "
                f"confidence={score.confidence:.2f})",
                extra={
                    "operation": "judge_complete",
                    "score": score.score,
                    "verdict": score.verdict.value,
                    "tokens_used": tokens_used,
                },
            )

        assert score is not None, "Judge Agent: score must be set if error boundary did not raise"

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent=AgentName.JUDGE,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.judge_agent.JudgeInput",
            output_schema="models.score.GreenwashingScore",
            llm_model_id=self._model_id,
            tokens_used=tokens_used,
            metadata={
                "score": score.score,
                "verdict": score.verdict.value,
                "confidence": score.confidence,
                "evidence_count": len(input.verification.evidence),
                "has_lobbying_record": input.lobbying is not None,
            },
        )

        return JudgeResult(score=score, trace=trace)

    @retry_async(config=RetryConfig.DEFAULT_LLM, operation="judge_llm_call")
    async def _call_llm(self, input: JudgeInput) -> tuple[dict[str, Any], int]:
        """Call the Anthropic API to produce the verdict.

        Builds a detailed user message from the full evidence package and
        forces the model to respond via the ``produce_verdict`` tool.

        Args:
            input: The complete evidence package.

        Returns:
            A tuple of (verdict_dict, tokens_used).

        Raises:
            :py:class:`~core.retry.LLMError`: On API failure or missing tool block.
        """
        user_message = _build_judge_prompt(input)

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
                tools=[_JUDGE_TOOL],
                tool_choice=anthropic.types.ToolChoiceToolParam(type="tool", name=_JUDGE_TOOL_NAME),
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIStatusError as exc:
            raise classify_anthropic_error(
                exc,
                agent=AgentName.JUDGE.value,
                llm_model_id=self._model_id,
            ) from exc

        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        tool_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if tool_block is None:
            raise LLMError(
                message=(
                    f"Judge model {self._model_id} returned no tool use block. "
                    f"Stop reason: {response.stop_reason!r}."
                ),
                agent=AgentName.JUDGE.value,
                retryable=False,
                llm_model_id=self._model_id,
            )

        return tool_block.input, tokens_used

    def _build_score(self, verdict: dict[str, Any], input: JudgeInput) -> GreenwashingScore:
        """Construct a GreenwashingScore from the LLM tool response.

        Args:
            verdict: The raw tool input dict from the LLM response.
            input: The original judge input (provides claim and company IDs).

        Returns:
            A validated :py:class:`~models.score.GreenwashingScore`.

        Raises:
            :py:class:`~core.retry.ExtractionError`: If the verdict dict
                cannot be parsed into a valid score.
        """
        try:
            return GreenwashingScore(
                claim_id=input.claim.id,
                company_id=input.context.company.id,
                trace_id=input.claim.trace_id,
                score=float(verdict["score"]),
                score_breakdown={
                    k: float(v)
                    for k, v in verdict.get("score_breakdown", {}).items()
                    if v is not None and str(v).strip().upper() not in ("N/A", "NA", "")
                },
                verdict=ScoreVerdict(verdict["verdict"]),
                reasoning=verdict["reasoning"],
                confidence=float(verdict.get("confidence", 0.7)),
                score_low=float(verdict["score_low"])
                if verdict.get("score_low") is not None
                else None,
                score_high=float(verdict["score_high"])
                if verdict.get("score_high") is not None
                else None,
                empco_violation=bool(verdict["empco_violation"])
                if verdict.get("empco_violation") is not None
                else None,
                judge_model_id=self._model_id,
                evidence_ids=[e.id for e in input.verification.evidence],
            )
        except Exception as exc:
            raise ExtractionError(
                message=f"Failed to parse judge verdict into GreenwashingScore: {exc}",
                agent=AgentName.JUDGE.value,
            ) from exc


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_judge_prompt(input: JudgeInput) -> str:
    """Construct the user message for the judge LLM call.

    Formats the complete evidence package as a structured text block that
    the model can reason over. Every field that affects the verdict is
    included explicitly; nothing is omitted to save tokens at this step.

    Args:
        input: The complete judge input.

    Returns:
        A formatted string suitable as the user message in the API call.
    """
    company = input.context.company
    ctx = input.context
    claim = input.claim
    vr = input.verification

    sections: list[str] = [
        "# CLAIM UNDER ASSESSMENT",
        f"Company:       {company.name} ({company.country})",
        f"Sector:        {company.sector}",
        f"CSRD obligated: {'Yes' if company.csrd_reporting else 'No'}",
        f"Category:      {claim.claim_category.value}",
        f"Source:        {claim.source_type.value} — {claim.source_url}",
        f"Published:     {claim.publication_date.date() if claim.publication_date else 'unknown'}",
        f"Page ref:      {claim.page_reference or 'not specified'}",
        "",
        "CLAIM TEXT (verbatim):",
        f'"{claim.raw_text}"',
        "",
        "# COMPANY HISTORICAL CONTEXT",
        f"Total prior claims assessed: {ctx.total_claims_assessed}",
        f"Prior repeat claims:         {ctx.repeat_claim_count}",
        f"Average greenwashing score:  {ctx.average_greenwashing_score:.1f}"
        if ctx.average_greenwashing_score is not None
        else "Average greenwashing score:  no prior data",
        f"Worst greenwashing score:    {ctx.worst_greenwashing_score:.1f}"
        if ctx.worst_greenwashing_score is not None
        else "Worst greenwashing score:    no prior data",
        f"Score trend:                 {ctx.score_trend.value}",
        f"Similar prior claims found:  {len(ctx.similar_historical_claim_ids)}",
        f"Is this a repeat claim:      {'YES — company has made equivalent claims before' if claim.is_repeat else 'No prior equivalent claims detected'}",
    ]

    sections += [
        "",
        "# VERIFICATION EVIDENCE",
        f"Sources queried: {', '.join(vr.sources_queried) if vr.sources_queried else 'EU_ETS, CDP, EUR_LEX'}",
        f"Data gaps: {'; '.join(vr.data_gaps) if vr.data_gaps else 'none'}",
        "",
        vr.overall_assessment,
        "",
        "INDIVIDUAL EVIDENCE RECORDS:",
    ]

    enforcement_records = [
        e for e in vr.evidence if e.evidence_type == EvidenceType.ENFORCEMENT_RULING
    ]
    other_records = [e for e in vr.evidence if e.evidence_type != EvidenceType.ENFORCEMENT_RULING]

    if enforcement_records:
        sections += [
            "",
            "REGULATORY ENFORCEMENT ACTIONS (highest-weight evidence — assess first):",
        ]
        for ev in enforcement_records:
            sections += [
                f"  Ruling body: {ev.source.value} | Year: {ev.data_year or 'N/A'} | Confidence: {ev.confidence:.2f}",
                f"  Supports claim: {ev.supports_claim}",
                f"  {ev.summary}",
            ]

    for i, ev in enumerate(other_records, 1):
        sections += [
            f"[{i}] Source: {ev.source.value} | Type: {ev.evidence_type.value} | "
            f"Year: {ev.data_year or 'N/A'} | Confidence: {ev.confidence:.2f}",
            f"    Supports claim: {ev.supports_claim}",
            f"    Summary: {ev.summary}",
        ]

    if input.lobbying:
        lb = input.lobbying
        sections += [
            "",
            "# LOBBYING RECORD (EU Transparency Register)",
            f"Registrant:     {lb.registrant_name}",
            f"Stance:         {lb.stance.value}",
            f"Reasoning:      {lb.stance_reasoning}",
            f"CONTRADICTS CLAIM: {'YES' if lb.contradicts_claim else 'No'}",
        ]
        if lb.contradiction_explanation:
            sections.append(f"Explanation:    {lb.contradiction_explanation}")
        if lb.fields_of_interest:
            sections.append(f"Fields of interest: {'; '.join(lb.fields_of_interest[:5])}")
    else:
        sections += [
            "",
            "# LOBBYING RECORD",
            "Not available: company not found in EU Transparency Register.",
        ]

    sections += [
        "",
        "Please assess this claim against all evidence above and produce your verdict "
        "using the produce_verdict tool.",
    ]

    return "\n".join(sections)

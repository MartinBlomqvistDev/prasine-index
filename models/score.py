"""Pydantic v2 model representing the Judge Agent's greenwashing verdict for a single claim.

The score is a calibrated 0–100 index where higher values indicate stronger
greenwashing evidence; the breakdown exposes per-dimension scores so that
published reports and investigative readers can interrogate the reasoning at a
granular level.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "GreenwashingScore",
    "ScoreCategory",
    "ScoreVerdict",
]


class ScoreCategory(StrEnum):
    """Dimensions used to decompose the overall greenwashing score.

    The Judge Agent produces a score for each applicable category; the overall
    score is a weighted aggregate. Categories that cannot be assessed due to data
    gaps are excluded from the aggregate and listed as absent in the breakdown.
    """

    EMISSIONS_DISCREPANCY = "EMISSIONS_DISCREPANCY"
    SUBSTANTIATION_FAILURE = "SUBSTANTIATION_FAILURE"
    PRIOR_VIOLATIONS = "PRIOR_VIOLATIONS"
    LOBBYING_CONTRADICTION = "LOBBYING_CONTRADICTION"
    TARGET_CREDIBILITY_GAP = "TARGET_CREDIBILITY_GAP"


class ScoreVerdict(StrEnum):
    """Human-readable verdict category derived from the overall score.

    These bands map score ranges to actionable labels used in published reports
    and the public-facing API. The top three verdicts describe the *claim*;
    the bottom two describe the *company*. Bands are equal-width (20 points each).

    0–20   SUBSTANTIATED_CLAIM    — verified data supports the claim.
    21–40  UNVERIFIABLE_CLAIM     — data gaps prevent assessment either way.
    41–60  MISLEADING_CLAIM       — claim misleads even if technically defensible.
    61–80  LIKELY_GREENWASHING    — material contradictions found; no binding ruling.
    81–100 CONFIRMED_GREENWASHING — binding ruling or multiple hard triggers.
    """

    SUBSTANTIATED_CLAIM = "SUBSTANTIATED_CLAIM"
    UNVERIFIABLE_CLAIM = "UNVERIFIABLE_CLAIM"
    MISLEADING_CLAIM = "MISLEADING_CLAIM"
    LIKELY_GREENWASHING = "LIKELY_GREENWASHING"
    CONFIRMED_GREENWASHING = "CONFIRMED_GREENWASHING"


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class GreenwashingScore(BaseModel):
    """The Judge Agent's calibrated greenwashing verdict for a single Claim.

    A score of 0 indicates a fully substantiated claim backed by verified data.
    A score of 100 indicates confirmed, well-evidenced greenwashing. Intermediate
    values reflect the weight and quality of contradicting evidence.

    The ``score_breakdown`` maps each assessed ScoreCategory to its individual
    score, enabling journalists and legal analysts to understand which dimension
    drove the overall verdict. Categories absent from the breakdown were not
    assessed due to data gaps.

    This model is frozen: judicial verdicts are immutable records. A revised
    assessment requires a new GreenwashingScore with a new ``id``.

    Attributes:
        id: Unique identifier for this score record.
        claim_id: The Claim that was judged.
        company_id: Denormalised company reference for efficient portfolio queries.
        trace_id: Pipeline-wide trace identifier, inherited from the Claim.
        score: Overall greenwashing index in [0.0, 100.0]. Higher = stronger
            greenwashing evidence.
        score_breakdown: Per-dimension scores keyed by ScoreCategory value.
            Only assessed categories are present.
        verdict: Human-readable verdict band derived from the overall score.
        reasoning: Judge Agent's full chain-of-thought reasoning, preserved
            verbatim for transparency and legal citation.
        confidence: Judge's confidence in the verdict, in [0.0, 1.0]. Reduced
            when key data sources were unavailable or returned conflicting signals.
        scored_at: UTC timestamp of when the Judge Agent produced this verdict.
        judge_model_id: Identifier of the LLM used to produce this verdict
            (e.g. ``"claude-opus-4-6"``). Preserved for reproducibility.
        evidence_ids: IDs of all Evidence records that were provided to the
            Judge Agent. Enables full evidence chain reconstruction.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    claim_id: uuid.UUID = Field(..., description="Foreign key to the judged Claim.")
    company_id: uuid.UUID = Field(
        ..., description="Denormalised company reference for portfolio-level queries."
    )
    trace_id: uuid.UUID = Field(
        ..., description="Pipeline trace identifier, inherited from the Claim."
    )
    score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description=(
            "Overall greenwashing index in [0.0, 100.0]. "
            "0 = fully substantiated claim; 100 = confirmed greenwashing."
        ),
    )
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-dimension scores keyed by ScoreCategory value. "
            "Only assessed categories are present; absent keys indicate data gaps."
        ),
    )
    verdict: ScoreVerdict = Field(
        ...,
        description="Human-readable verdict band derived from the overall score.",
    )
    reasoning: str = Field(
        ...,
        description=(
            "Judge Agent's full chain-of-thought reasoning, preserved verbatim "
            "for transparency and legal citation."
        ),
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Judge's confidence in the verdict, in [0.0, 1.0]. "
            "Reduced when key data sources were unavailable or signals were conflicting."
        ),
    )
    score_low: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Lower bound of the plausible score range, accounting for data uncertainty.",
    )
    score_high: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
        description="Upper bound of the plausible score range, accounting for data uncertainty.",
    )
    scored_at: datetime = Field(
        default_factory=_utc_now,
        description="UTC timestamp of when the Judge Agent produced this verdict.",
    )
    judge_model_id: str = Field(
        ...,
        description="LLM identifier used to produce this verdict (e.g. 'claude-opus-4-6'). Preserved for reproducibility.",
    )
    evidence_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="IDs of all Evidence records provided to the Judge Agent; enables full evidence chain reconstruction.",
    )
    empco_violation: bool | None = Field(
        default=None,
        description=(
            "Whether this claim violates the EmpCo Directive (EU 2024/825). "
            "True = confirmed violation (e.g. offset-based net-zero claim without certified permanent removals, "
            "or a claim that fails the mandatory substantiation standard). "
            "False = no EmpCo violation found. "
            "None = not assessed (insufficient data, claim type out of scope, or pre-EmpCo archive)."
        ),
    )

    @model_validator(mode="after")
    def _validate_breakdown_scores(self) -> GreenwashingScore:
        """Validate that all breakdown dimension scores are in [0.0, 100.0].

        Returns:
            The validated GreenwashingScore instance.

        Raises:
            ValueError: If any dimension score falls outside [0.0, 100.0].
        """
        for category, dimension_score in self.score_breakdown.items():
            if not (0.0 <= dimension_score <= 100.0):
                raise ValueError(
                    f"score_breakdown[{category!r}] = {dimension_score} is outside [0.0, 100.0]."
                )
        return self

    @model_validator(mode="after")
    def _validate_breakdown_keys(self) -> GreenwashingScore:
        """Validate that all breakdown keys are valid ScoreCategory values.

        Returns:
            The validated GreenwashingScore instance.

        Raises:
            ValueError: If any key in ``score_breakdown`` is not a valid
                ``ScoreCategory`` value.
        """
        valid_categories = {c.value for c in ScoreCategory}
        for key in self.score_breakdown:
            if key not in valid_categories:
                raise ValueError(
                    f"score_breakdown key {key!r} is not a valid ScoreCategory. "
                    f"Valid values: {sorted(valid_categories)}"
                )
        return self

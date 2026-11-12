"""Pydantic v2 model of the Judge Agent's score for a single claim.

The score is a 0–100 index of how far the records go against a claim, from 0
(the records support it) to 100 (an official record shows it to be false); the
breakdown gives a score per dimension so that the reasoning can be read in
detail.
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
    "band_floor",
    "verdict_for_score",
]


class ScoreCategory(StrEnum):
    """Dimensions used to decompose the overall score.

    The Judge Agent scores each dimension it can assess, alongside the overall
    score. A dimension that cannot be assessed, or that the band rules do not let
    bear on the claim, is left out of the breakdown.
    """

    EMISSIONS_DISCREPANCY = "EMISSIONS_DISCREPANCY"
    SUBSTANTIATION_FAILURE = "SUBSTANTIATION_FAILURE"
    PRIOR_VIOLATIONS = "PRIOR_VIOLATIONS"
    LOBBYING_CONTRADICTION = "LOBBYING_CONTRADICTION"
    TARGET_CREDIBILITY_GAP = "TARGET_CREDIBILITY_GAP"


class ScoreVerdict(StrEnum):
    """The band of a score.

    The names date from version 1 and are internal; FINDING_LABELS holds the
    published name of each band.

    0–20   SUBSTANTIATED_CLAIM   : Supported by records.
    21–40  UNVERIFIABLE_CLAIM    : Not covered by public records.
    41–60  MISLEADING_CLAIM      : Not fully supported.
    61–80  LIKELY_GREENWASHING   : Conflicts with records.
    81–100 CONFIRMED_GREENWASHING: Contradicted by records.
    """

    SUBSTANTIATED_CLAIM = "SUBSTANTIATED_CLAIM"
    UNVERIFIABLE_CLAIM = "UNVERIFIABLE_CLAIM"
    MISLEADING_CLAIM = "MISLEADING_CLAIM"
    LIKELY_GREENWASHING = "LIKELY_GREENWASHING"
    CONFIRMED_GREENWASHING = "CONFIRMED_GREENWASHING"


# The published name of each band. The enum values are internal and are never
# shown to readers.
FINDING_LABELS: dict[ScoreVerdict, str] = {
    ScoreVerdict.SUBSTANTIATED_CLAIM: "Supported by records",
    ScoreVerdict.UNVERIFIABLE_CLAIM: "Not covered by public records",
    ScoreVerdict.MISLEADING_CLAIM: "Not fully supported",
    ScoreVerdict.LIKELY_GREENWASHING: "Conflicts with records",
    ScoreVerdict.CONFIRMED_GREENWASHING: "Contradicted by records",
}


def finding_label(verdict: ScoreVerdict) -> str:
    """Return the published name of a score band."""
    return FINDING_LABELS[verdict]


def verdict_for_score(score: float) -> ScoreVerdict:
    """Derive the verdict band from a numeric score.

    The numeric score is the single source of truth for the verdict, at both
    claim level (Judge Agent) and company level (aggregate). Bands:
    0–20 SUBSTANTIATED_CLAIM, 21–40 UNVERIFIABLE_CLAIM, 41–60 MISLEADING_CLAIM,
    61–80 LIKELY_GREENWASHING, 81–100 CONFIRMED_GREENWASHING.

    Args:
        score: Score in [0.0, 100.0].

    Returns:
        The :py:class:`ScoreVerdict` band for the score.
    """
    if score <= 20.0:
        return ScoreVerdict.SUBSTANTIATED_CLAIM
    if score <= 40.0:
        return ScoreVerdict.UNVERIFIABLE_CLAIM
    if score <= 60.0:
        return ScoreVerdict.MISLEADING_CLAIM
    if score <= 80.0:
        return ScoreVerdict.LIKELY_GREENWASHING
    return ScoreVerdict.CONFIRMED_GREENWASHING


def band_floor(score: float) -> float:
    """Return the lower bound of the verdict band the score falls in.

    Used by the company-level aggregate: a confirmed (or otherwise severe)
    finding cannot be averaged away, so the company score is floored at the
    bottom of the worst claim's band. Floors: 0, 21, 41, 61, 81.

    Args:
        score: Score in [0.0, 100.0].

    Returns:
        The band floor as a float.
    """
    if score <= 20.0:
        return 0.0
    if score <= 40.0:
        return 21.0
    if score <= 60.0:
        return 41.0
    if score <= 80.0:
        return 61.0
    return 81.0


def _utc_now() -> datetime:
    """Return the current UTC-aware datetime.

    Returns:
        The current datetime with UTC timezone set.
    """
    return datetime.now(UTC)


class GreenwashingScore(BaseModel):
    """The Judge Agent's score for a single Claim.

    A score of 0 means the records support the claim; a score of 100 means an
    official record shows it to be false. Intermediate values reflect the weight
    and quality of the records against the claim.

    The ``score_breakdown`` maps each assessed ScoreCategory to its individual
    score, so that a reader can see which dimension drove the overall score.
    Categories absent from the breakdown were not assessed, or do not bear on the
    claim under the band rules.

    This model is frozen: a score is an immutable record. A revised assessment
    requires a new GreenwashingScore with a new ``id``.

    Attributes:
        id: Unique identifier for this score record.
        claim_id: The Claim that was judged.
        company_id: Denormalised company reference for efficient portfolio queries.
        trace_id: Pipeline-wide trace identifier, inherited from the Claim.
        score: Score in [0.0, 100.0]; higher means the records go further
            against the claim.
        score_breakdown: Per-dimension scores keyed by ScoreCategory value.
            Only dimensions the judge assessed, and that the band rules let
            bear on the claim, are present.
        verdict: Band derived from the overall score; FINDING_LABELS holds its
            published name.
        reasoning: The Judge Agent's written explanation of the score, preserved
            verbatim.
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
            "Score in [0.0, 100.0]. "
            "0 = the records support the claim; 100 = an official record shows it to be false."
        ),
    )
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-dimension scores keyed by ScoreCategory value. Only dimensions the "
            "judge assessed, and that the band rules let bear on the claim, are present."
        ),
    )
    verdict: ScoreVerdict = Field(
        ...,
        description="Band derived from the overall score; FINDING_LABELS holds its published name.",
    )
    reasoning: str = Field(
        ...,
        description="The Judge Agent's written explanation of the score, preserved verbatim.",
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
    claim_is_pledge: bool = Field(
        default=False,
        description="Whether the judge found the claim's central statement to be a company-wide climate pledge.",
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
    contradicting_evidence_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="IDs of the claim-level Evidence records the judge found to contradict this claim.",
    )
    supporting_evidence_ids: list[uuid.UUID] = Field(
        default_factory=list,
        description="IDs of the claim-level Evidence records the judge found to support this claim.",
    )
    empco_violation: bool | None = Field(
        default=None,
        description=(
            "Deprecated; kept so rows written before November 2026 still load. "
            "The pipeline no longer produces a legal-violation flag: whether a practice "
            "breaches Directive (EU) 2024/825 is for national authorities and courts to "
            "decide, case by case. New verdicts leave this None."
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

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

    EMISSIONS_ACCURACY = "EMISSIONS_ACCURACY"
    CLAIM_SUBSTANTIATION = "CLAIM_SUBSTANTIATION"
    HISTORICAL_CONSISTENCY = "HISTORICAL_CONSISTENCY"
    LOBBYING_ALIGNMENT = "LOBBYING_ALIGNMENT"
    TARGET_CREDIBILITY = "TARGET_CREDIBILITY"


class ScoreVerdict(StrEnum):
    """Human-readable verdict category derived from the overall score.

    These bands map score ranges to actionable labels used in published reports
    and the public-facing API. The bands are intentionally conservative to avoid
    false positives in published material intended for legal and journalistic use.
    """

    SUBSTANTIATED = "SUBSTANTIATED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    MISLEADING = "MISLEADING"
    GREENWASHING = "GREENWASHING"
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

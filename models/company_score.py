"""Company-level aggregate score across multiple assessed claims."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from models.score import ScoreVerdict

__all__ = ["ClaimSummary", "CompanyScore"]


class ClaimSummary(BaseModel):
    """Score summary for one assessed claim within a company-level assessment."""

    model_config = ConfigDict(frozen=True)

    claim_text: str = Field(description="First 200 chars of the raw claim text.")
    score: float = Field(ge=0.0, le=100.0)
    score_low: float | None = Field(default=None, ge=0.0, le=100.0)
    score_high: float | None = Field(default=None, ge=0.0, le=100.0)
    verdict: ScoreVerdict
    confidence: float = Field(ge=0.0, le=1.0)


class CompanyScore(BaseModel):
    """Company-level aggregate across all claims assessed for a company.

    Score is the confidence-weighted mean of the top-3 highest-scoring claims,
    floored at the bottom of the worst claim's verdict band — a confirmed
    finding cannot be averaged away by milder claims. Verdict is derived from
    the final numeric score, so score and verdict can never disagree.
    Confidence is the weighted mean of individual claim confidences.
    """

    model_config = ConfigDict(frozen=True)

    company_name: str
    company_id: uuid.UUID
    score: float = Field(
        ge=0.0,
        le=100.0,
        description="Top-3 severity-weighted score, floored at the worst claim's band.",
    )
    score_low: float = Field(ge=0.0, le=100.0)
    score_high: float = Field(ge=0.0, le=100.0)
    verdict: ScoreVerdict = Field(description="Verdict band derived from the aggregate score.")
    confidence: float = Field(ge=0.0, le=1.0, description="Mean confidence across claims.")
    claim_count: int = Field(ge=1)
    claims: list[ClaimSummary]
    floor_applied: bool = Field(
        default=False,
        description=(
            "True when the aggregate was raised to the worst claim's band floor — "
            "i.e. milder claims would otherwise have averaged a severe finding "
            "into a lower band."
        ),
    )
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

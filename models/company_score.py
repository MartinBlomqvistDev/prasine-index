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
    """Confidence-weighted aggregate across all claims assessed for a company.

    Score is the confidence-weighted mean of individual claim scores.
    Verdict is the highest-severity verdict found across all claims.
    Confidence is the mean of individual claim confidences.
    """

    model_config = ConfigDict(frozen=True)

    company_name: str
    company_id: uuid.UUID
    score: float = Field(ge=0.0, le=100.0, description="Confidence-weighted mean score.")
    score_low: float = Field(ge=0.0, le=100.0)
    score_high: float = Field(ge=0.0, le=100.0)
    verdict: ScoreVerdict = Field(description="Highest-severity verdict across all claims.")
    confidence: float = Field(ge=0.0, le=1.0, description="Mean confidence across claims.")
    claim_count: int = Field(ge=1)
    claims: list[ClaimSummary]
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

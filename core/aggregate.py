"""Aggregate multiple claim-level pipeline results into a company-level score."""

from __future__ import annotations

import uuid

from core.pipeline import PipelineResult
from models.company_score import ClaimSummary, CompanyScore
from models.score import ScoreVerdict

__all__ = ["aggregate_claim_scores"]

# Severity order used to pick the dominant verdict.
_SEVERITY: dict[ScoreVerdict, int] = {
    ScoreVerdict.SUBSTANTIATED_CLAIM: 0,
    ScoreVerdict.UNVERIFIABLE_CLAIM: 1,
    ScoreVerdict.MISLEADING_CLAIM: 2,
    ScoreVerdict.LIKELY_GREENWASHING: 3,
    ScoreVerdict.CONFIRMED_GREENWASHING: 4,
}

# Score is computed from the top K claims by severity. The remaining claims
# appear in the report for context but don't drive the headline number.
# Rationale: a verified freshwater reduction shouldn't dilute the score for
# a confirmed net-zero greenwashing claim — they're different signal types.
_SCORE_TOP_K = 3


def _weighted_agg(subset: list[ClaimSummary]) -> tuple[float, float, float, float]:
    """Return (score, low, high, confidence) weighted by confidence × score."""
    weights = [s.confidence * s.score for s in subset]
    total = sum(weights)
    if total == 0:
        n = len(subset)
        return (
            sum(s.score for s in subset) / n,
            sum((s.score_low or s.score) for s in subset) / n,
            sum((s.score_high or s.score) for s in subset) / n,
            0.0,
        )
    return (
        sum(s.score * w for s, w in zip(subset, weights, strict=True)) / total,
        sum((s.score_low or s.score) * w for s, w in zip(subset, weights, strict=True)) / total,
        sum((s.score_high or s.score) * w for s, w in zip(subset, weights, strict=True)) / total,
        sum(s.confidence * w for s, w in zip(subset, weights, strict=True)) / total,
    )


def aggregate_claim_scores(
    company_name: str,
    company_id: uuid.UUID,
    results: list[PipelineResult],
) -> CompanyScore:
    """Build a company-level aggregate from per-claim pipeline results.

    Args:
        company_name: Human-readable company name.
        company_id: Pipeline UUID for this company.
        results: Non-empty list of completed pipeline results.

    Returns:
        A :py:class:`~models.company_score.CompanyScore` with top-K severity-weighted
        score and highest-severity dominant verdict across all claims.

    Raises:
        ValueError: If *results* is empty.
    """
    if not results:
        raise ValueError("Cannot aggregate an empty results list.")

    summaries = [
        ClaimSummary(
            claim_text=(r.claim.raw_text or "")[:200],
            score=r.score.score,
            score_low=r.score.score_low,
            score_high=r.score.score_high,
            verdict=r.score.verdict,
            confidence=r.score.confidence,
        )
        for r in results
    ]

    # Score on the top-K most severe claims only.
    top_k = sorted(summaries, key=lambda s: s.score, reverse=True)[:_SCORE_TOP_K]
    agg_score, agg_low, agg_high, agg_conf = _weighted_agg(top_k)

    # Dominant verdict from ALL claims — worst-case finding across the full assessment.
    dominant = max(summaries, key=lambda s: _SEVERITY[s.verdict]).verdict

    return CompanyScore(
        company_name=company_name,
        company_id=company_id,
        score=round(agg_score, 1),
        score_low=round(agg_low, 1),
        score_high=round(agg_high, 1),
        verdict=dominant,
        confidence=round(agg_conf, 3),
        claim_count=len(summaries),
        claims=summaries,
    )

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
        A :py:class:`~models.company_score.CompanyScore` with confidence-weighted
        score and highest-severity verdict.

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

    # Weight each claim by confidence × score so high-severity confirmed claims
    # dominate the aggregate rather than being averaged down by substantiated ones.
    weights = [s.confidence * s.score for s in summaries]
    total_weight = sum(weights)
    if total_weight == 0:
        n = len(summaries)
        agg_score = sum(s.score for s in summaries) / n
        agg_low = sum((s.score_low or s.score) for s in summaries) / n
        agg_high = sum((s.score_high or s.score) for s in summaries) / n
        agg_conf = 0.0
    else:
        agg_score = sum(s.score * w for s, w in zip(summaries, weights, strict=True)) / total_weight
        agg_low = (
            sum((s.score_low or s.score) * w for s, w in zip(summaries, weights, strict=True))
            / total_weight
        )
        agg_high = (
            sum((s.score_high or s.score) * w for s, w in zip(summaries, weights, strict=True))
            / total_weight
        )
        agg_conf = (
            sum(s.confidence * w for s, w in zip(summaries, weights, strict=True)) / total_weight
        )

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

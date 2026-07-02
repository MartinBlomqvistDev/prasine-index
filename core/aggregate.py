"""Aggregate multiple claim-level pipeline results into a company-level score."""

from __future__ import annotations

import uuid

from core.pipeline import PipelineResult
from models.company_score import ClaimSummary, CompanyScore
from models.score import band_floor, verdict_for_score

__all__ = ["aggregate_claim_scores"]

# Score is computed from the top K claims by severity. The remaining claims
# appear in the report for context but don't drive the headline number.
# Rationale: a verified freshwater reduction shouldn't dilute the score for
# a confirmed net-zero greenwashing claim — they're different signal types.
_SCORE_TOP_K = 3


def _weighted_agg(subset: list[ClaimSummary]) -> tuple[float, float, float, float]:
    """Return (score, low, high, confidence) as confidence-weighted means.

    Weights are the judge's per-claim confidences only. Using score as its own
    weight (the previous confidence × score scheme) double-counted severity —
    the formula must be describable in one sentence for legal defensibility:
    "the confidence-weighted mean of the three highest-scoring claims".
    Severity protection comes from the band floor in the caller, not from
    weight gymnastics here.
    """
    weights = [s.confidence for s in subset]
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
        A :py:class:`~models.company_score.CompanyScore` with a top-K
        severity-weighted score, floored at the bottom of the worst claim's
        verdict band, and a verdict derived from that final score.

    Raises:
        ValueError: If *results* is empty.

    Aggregation rule: the score is the confidence-weighted mean of the top-K
    highest-scoring claims, but it can never fall below the band floor of the
    single worst claim — a confirmed finding cannot be averaged away. The
    company verdict is always derived from the final numeric score, so score
    and verdict can never disagree.
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

    # Floor at the worst claim's band: a confirmed (or otherwise severe)
    # finding cannot be averaged away by milder claims.
    worst_score = max(s.score for s in summaries)
    floor = band_floor(worst_score)
    floor_applied = agg_score < floor
    if floor_applied:
        agg_score = floor
        agg_low = max(agg_low, floor)
        agg_high = max(agg_high, floor)

    return CompanyScore(
        company_name=company_name,
        company_id=company_id,
        score=round(agg_score, 1),
        score_low=round(agg_low, 1),
        score_high=round(agg_high, 1),
        verdict=verdict_for_score(round(agg_score, 1)),
        confidence=round(agg_conf, 3),
        claim_count=len(summaries),
        claims=summaries,
        floor_applied=floor_applied,
    )

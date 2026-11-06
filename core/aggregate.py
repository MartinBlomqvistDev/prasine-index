"""Aggregate multiple claim-level pipeline results into a company-level score."""

from __future__ import annotations

import math
import re
import uuid

from core.pipeline import PipelineResult
from models.company_score import ClaimSummary, CompanyScore
from models.score import band_floor, verdict_for_score

__all__ = ["aggregate_claim_scores"]

# Score is computed from the top K claims by severity. The remaining claims
# appear in the report for context but don't drive the headline number.
# Rationale: a verified freshwater reduction shouldn't dilute the score for
# a confirmed net-zero greenwashing claim: they're different signal types.
_SCORE_TOP_K = 3

# Target years a pledge names, such as "net zero by 2040", "FY30" or "FY2030".
_YEAR = re.compile(r"(?<!\d)(20[2-9]\d|2100)(?!\d)")
_FISCAL_YEAR = re.compile(r"\bFY ?(\d{2})(?!\d)", re.IGNORECASE)

# Words that say which emissions a pledge covers. Two pledges for the same year that
# cover different emissions, such as operations and products sold, are two pledges.
_SCOPE_WORDS = (
    ("scope 1", "scope 1"),
    ("scope 2", "scope 2"),
    ("scope 3", "scope 3"),
    ("operation", "operations"),
    ("product", "products"),
    ("sold", "products"),
    ("value chain", "value chain"),
    ("supply chain", "supply chain"),
)


def _pledge_key(result: PipelineResult) -> tuple[frozenset[str], frozenset[str]] | None:
    """Return the target years and the emissions a pledge covers, or None for no pledge."""
    if not result.score.claim_is_pledge:
        return None
    text = result.claim.raw_text or ""
    years = {*_YEAR.findall(text), *(f"20{yy}" for yy in _FISCAL_YEAR.findall(text))}
    if not years:
        return None
    lowered = text.lower()
    scope = frozenset(tag for word, tag in _SCOPE_WORDS if word in lowered)
    return frozenset(years), scope


def _distinct_pledges(results: list[PipelineResult]) -> tuple[list[int], int]:
    """Return the indexes of the claims that enter the mean, and how many were left out.

    Claims the judge found to be pledges that name the same target years and cover the
    same emissions state the same pledge, which counts once, through the
    highest-scoring of those claims. Every other claim enters as it is.
    """
    best: dict[tuple[frozenset[str], frozenset[str]], int] = {}
    keep: list[int] = []
    for index, result in enumerate(results):
        key = _pledge_key(result)
        if key is None:
            keep.append(index)
        elif key not in best or result.score.score > results[best[key]].score.score:
            best[key] = index
    keep += best.values()
    return sorted(keep), len(results) - len(keep)


def _whole(value: float) -> float:
    """Round half up to a whole number, once, so that 46.52 is 47 and 55.49 is 55."""
    return float(math.floor(value + 0.5))


def _weighted_agg(subset: list[ClaimSummary]) -> tuple[float, float, float, float]:
    """Return (score, low, high, confidence) as confidence-weighted means.

    Weights are the judge's per-claim confidences only. Using score as its own
    weight (the previous confidence × score scheme) double-counted severity:
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
        A :py:class:`~models.company_score.CompanyScore` whose score is the
        confidence-weighted mean of the top-K claims, floored at the bottom of
        the highest-scoring claim's band, with a finding derived from that score.

    Raises:
        ValueError: If *results* is empty.

    Aggregation rule: the score is the confidence-weighted mean of the top-K
    highest-scoring claims, but it can never fall below the band floor of the
    single worst claim; a confirmed finding cannot be averaged away. The
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

    # Score on the top-K most severe claims only, with each pledge counted once. Of two
    # claims with the same score, the one the judge is more confident in comes first.
    entering, counted_once = _distinct_pledges(results)
    top_k = sorted(
        (summaries[i] for i in entering), key=lambda s: (s.score, s.confidence), reverse=True
    )[:_SCORE_TOP_K]
    agg_score, agg_low, agg_high, agg_conf = _weighted_agg(top_k)

    # Floor at the worst claim's band: a confirmed (or otherwise severe)
    # finding cannot be averaged away by milder claims.
    worst_score = max(s.score for s in summaries)
    floor = band_floor(worst_score)
    floor_applied = _whole(agg_score) < floor
    mean_score = agg_score
    if floor_applied:
        # Only the score is raised. The range stays the mean of the judge's own low and
        # high estimates, so it is what the published label says it is.
        agg_score = floor

    return CompanyScore(
        company_name=company_name,
        company_id=company_id,
        score=_whole(agg_score),
        score_low=_whole(agg_low),
        score_high=_whole(agg_high),
        verdict=verdict_for_score(_whole(agg_score)),
        confidence=round(agg_conf, 3),
        claim_count=len(summaries),
        claims=summaries,
        floor_applied=floor_applied,
        mean_score=_whole(mean_score),
        pledges_counted_once=counted_once,
    )

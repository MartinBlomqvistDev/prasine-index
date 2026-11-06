"""Aggregate multiple claim-level pipeline results into a company-level score."""

from __future__ import annotations

import math
import re
import uuid
from datetime import UTC, datetime

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
_FISCAL_YEAR = re.compile(r"\bFY ?(\d{2}|20\d{2})(?!\d)", re.IGNORECASE)

# Which emissions a pledge covers. Two pledges for the same year that cover different
# emissions, such as operations and products sold, are two pledges. Scope lists are read
# as sets ("Scope 1, 2 and 3", "Scopes 1-3"), and words are matched whole.
_SCOPES = re.compile(
    r"\bscopes?\s*([123](?!\d)(?:\s*(?:,\s*(?:and|&)|,|and|&|\+|/|-|\u2013|to)\s*[123](?!\d))*)",
    re.IGNORECASE,
)
_SCOPE_WORDS = (
    (
        re.compile(r"\boperations?\b|\boperational\b|\bmanufactur\w*", re.IGNORECASE),
        "operations",
    ),
    # An oil and gas producer's production is neither its operations nor its products.
    (re.compile(r"\bproduction\b", re.IGNORECASE), "production"),
    (re.compile(r"\bproducts?\b|\bsold\b", re.IGNORECASE), "products"),
    (re.compile(r"\bvalue chain\b", re.IGNORECASE), "value chain"),
    (re.compile(r"\bsupply chain\b", re.IGNORECASE), "supply chain"),
)


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _named_years(text: str) -> set[str]:
    """Return the years a text names, reading "FY30" and "FY2030" as "2030"."""
    return {*_YEAR.findall(text), *(f"20{y[-2:]}" for y in _FISCAL_YEAR.findall(text))}


def _scope_numbers(text: str) -> set[str]:
    """Return the scopes a text names, as "scope 1" and so on, expanding "1-3" and "1 to 3"."""
    found: set[str] = set()
    for listed in _SCOPES.findall(text):
        digits = [int(d) for d in re.findall(r"[123]", listed)]
        if len(digits) == 2 and re.search(r"-|\u2013|to", listed):
            digits = list(range(min(digits), max(digits) + 1))
        found.update(f"scope {d}" for d in digits)
    return found


def _pledge_key(result: PipelineResult) -> tuple[frozenset[str], frozenset[str]] | None:
    """Return the target years and the emissions a pledge covers, or None for no pledge."""
    if not result.score.claim_is_pledge:
        return None
    text = result.claim.raw_text or ""
    # Target years only: a base year or a year already past is not what a pledge names.
    this_year = datetime.now(UTC).year
    years = {year for year in _named_years(text) if int(year) > this_year}
    if not years:
        return None
    # The emissions are read from the sentences that state the target, so that a sentence
    # about something else, such as removals, does not change the key.
    stating = " ".join(s for s in _SENTENCE.split(text) if _named_years(s) & years) or text
    scope = frozenset(
        _scope_numbers(stating) | {tag for pattern, tag in _SCOPE_WORDS if pattern.search(stating)}
    )
    return frozenset(years), scope


def _distinct_pledges(results: list[PipelineResult]) -> tuple[list[int], int]:
    """Return the indexes of the claims that enter the mean, and how many were left out.

    Claims the judge found to be pledges that name the same target years and cover the
    same emissions state the same pledge, which counts once, through the
    highest-scoring of those claims. Every other claim enters as it is.
    """
    keys = [_pledge_key(result) for result in results]
    # A pledge that names no emissions joins the group with the same years that does,
    # when there is exactly one such group.
    for i, key in enumerate(keys):
        if key is not None and not key[1]:
            scoped = {k for k in keys if k is not None and k[0] == key[0] and k[1]}
            if len(scoped) == 1:
                keys[i] = next(iter(scoped))
    best: dict[tuple[frozenset[str], frozenset[str]], int] = {}
    keep: list[int] = []
    for index, result in enumerate(results):
        key = keys[index]
        if key is None:
            keep.append(index)
        elif key not in best or (result.score.score, result.score.confidence) > (
            results[best[key]].score.score,
            results[best[key]].score.confidence,
        ):
            best[key] = index
    keep += best.values()
    return sorted(keep), len(results) - len(keep)


def _whole(value: float) -> float:
    """Round half up to a whole number, once, so that 46.52 is 47 and 55.49 is 55."""
    return float(math.floor(round(value, 9) + 0.5))


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
        # A whole percent, rounded once, so that the published figure is this one.
        confidence=math.floor(round(agg_conf * 100, 9) + 0.5) / 100,
        claim_count=len(summaries),
        claims=summaries,
        floor_applied=floor_applied,
        mean_score=_whole(mean_score),
        pledges_counted_once=counted_once,
    )

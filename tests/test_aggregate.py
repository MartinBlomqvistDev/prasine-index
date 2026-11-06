"""Tests for the company-level aggregate: band helpers and worst-claim floor.

Pure-Python: no LLM calls, no network, no database.
"""

from __future__ import annotations

import uuid

import pytest

from core.aggregate import aggregate_claim_scores
from core.pipeline import PipelineResult
from models.claim import Claim, ClaimCategory, ClaimStatus, SourceType
from models.score import GreenwashingScore, ScoreVerdict, band_floor, verdict_for_score

_COMPANY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _result(score: float, confidence: float = 0.8) -> PipelineResult:
    """Build a minimal PipelineResult with the given claim score."""
    trace_id = uuid.uuid4()
    claim = Claim(
        trace_id=trace_id,
        company_id=_COMPANY_ID,
        source_url="https://example.com/sustainability",
        source_type=SourceType.WEBSITE,
        raw_text=f"Test claim scoring {score}",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        status=ClaimStatus.SCORED,
    )
    gw_score = GreenwashingScore(
        claim_id=claim.id,
        company_id=_COMPANY_ID,
        trace_id=trace_id,
        score=score,
        verdict=verdict_for_score(score),
        reasoning="test",
        confidence=confidence,
        judge_model_id="test-model",
    )
    return PipelineResult(claim=claim, score=gw_score, report_markdown="# test")


class TestVerdictForScore:
    @pytest.mark.parametrize(
        ("score", "expected"),
        [
            (0.0, ScoreVerdict.SUBSTANTIATED_CLAIM),
            (20.0, ScoreVerdict.SUBSTANTIATED_CLAIM),
            (20.5, ScoreVerdict.UNVERIFIABLE_CLAIM),
            (40.0, ScoreVerdict.UNVERIFIABLE_CLAIM),
            (41.0, ScoreVerdict.MISLEADING_CLAIM),
            (60.0, ScoreVerdict.MISLEADING_CLAIM),
            (61.0, ScoreVerdict.LIKELY_GREENWASHING),
            (80.0, ScoreVerdict.LIKELY_GREENWASHING),
            (81.0, ScoreVerdict.CONFIRMED_GREENWASHING),
            (100.0, ScoreVerdict.CONFIRMED_GREENWASHING),
        ],
    )
    def test_band_boundaries(self, score: float, expected: ScoreVerdict) -> None:
        assert verdict_for_score(score) == expected


class TestBandFloor:
    @pytest.mark.parametrize(
        ("score", "expected_floor"),
        [(10.0, 0.0), (30.0, 21.0), (52.0, 41.0), (70.0, 61.0), (86.0, 81.0)],
    )
    def test_floors(self, score: float, expected_floor: float) -> None:
        assert band_floor(score) == expected_floor


class TestAggregateFloor:
    def test_confirmed_claim_cannot_be_averaged_away(self) -> None:
        """BP case: claims at 86, 85, 62 average below 81 but must floor at 81."""
        results = [_result(86.0), _result(85.0), _result(62.0), _result(18.0)]
        company = aggregate_claim_scores("BP plc", _COMPANY_ID, results)
        assert company.score >= 81.0
        assert company.verdict == ScoreVerdict.CONFIRMED_GREENWASHING
        assert company.floor_applied is True
        # The range stays the mean of the judge's estimates; only the score is raised.
        assert company.mean_score is not None and company.mean_score < 81.0

    def test_misleading_claim_floors_out_of_unverifiable(self) -> None:
        """H&M case: worst claim 52 (misleading) floors the aggregate at 41."""
        results = [_result(52.0), _result(33.0), _result(24.0), _result(22.0)]
        company = aggregate_claim_scores("H&M Group", _COMPANY_ID, results)
        assert company.score >= 41.0
        assert company.verdict == ScoreVerdict.MISLEADING_CLAIM
        assert company.floor_applied is True

    def test_no_floor_when_aggregate_already_in_band(self) -> None:
        """Ryanair case: all top claims confirmed; aggregate sits in band naturally."""
        results = [_result(86.0), _result(86.0), _result(85.0)]
        company = aggregate_claim_scores("Ryanair", _COMPANY_ID, results)
        assert company.score >= 81.0
        assert company.verdict == ScoreVerdict.CONFIRMED_GREENWASHING
        assert company.floor_applied is False

    def test_verdict_always_matches_score_band(self) -> None:
        results = [_result(58.0), _result(54.0), _result(52.0), _result(22.0)]
        company = aggregate_claim_scores("Enel SpA", _COMPANY_ID, results)
        assert verdict_for_score(company.score) == company.verdict

    def test_empty_results_raise(self) -> None:
        with pytest.raises(ValueError):
            aggregate_claim_scores("Empty", _COMPANY_ID, [])


def _stated(score: float, text: str, pledge: bool = True) -> PipelineResult:
    """A claim with its own text, which the judge did or did not find to be a pledge."""
    result = _result(score)
    return PipelineResult(
        claim=result.claim.model_copy(update={"raw_text": text}),
        score=result.score.model_copy(update={"claim_is_pledge": pledge}),
        report_markdown="# test",
    )


class TestPledgeCountedOnce:
    """A pledge stated in several claims enters the mean once, through its highest score."""

    def test_the_same_pledge_counts_once(self) -> None:
        results = [
            _stated(48.0, "The Group confirms its objective to achieve net zero by 2040."),
            _stated(57.0, "From 2040 onwards, consistent with the net zero target, ..."),
            _result(43.0),
            _result(42.0),
        ]
        company = aggregate_claim_scores("Enel SpA", _COMPANY_ID, results)
        assert company.pledges_counted_once == 1
        assert company.mean_score == 47.0  # (57 + 43 + 42) / 3, rounded once
        assert company.claim_count == 4

    def test_pledges_with_different_years_both_count(self) -> None:
        results = [
            _stated(50.0, "Net zero by 2040."),
            _stated(45.0, "Halve emissions by 2030."),
            _result(44.0),
        ]
        company = aggregate_claim_scores("X", _COMPANY_ID, results)
        assert company.pledges_counted_once == 0

    def test_statements_of_fact_are_not_grouped(self) -> None:
        results = [
            _stated(50.0, "Our 2040 target was validated.", pledge=False),
            _stated(45.0, "We cut emissions 40% towards 2040.", pledge=False),
        ]
        company = aggregate_claim_scores("X", _COMPANY_ID, results)
        assert company.pledges_counted_once == 0

    def test_pledges_for_different_emissions_both_count(self) -> None:
        results = [
            _stated(66.0, "Net zero across our operations by 2050 or sooner."),
            _stated(64.0, "Net zero for the carbon intensity of the products we sell by 2050."),
            _result(42.0),
        ]
        company = aggregate_claim_scores("BP plc", _COMPANY_ID, results)
        assert company.pledges_counted_once == 0

    def test_fiscal_years_name_the_same_pledge(self) -> None:
        results = [
            _stated(40.0, "Halve emissions by FY30 and reach net zero by FY50."),
            _stated(38.0, "Halve emissions by 2030 and reach net zero by 2050."),
            _result(30.0),
        ]
        company = aggregate_claim_scores("IKEA", _COMPANY_ID, results)
        assert company.pledges_counted_once == 1


class TestRounding:
    def test_rounds_once_half_up(self) -> None:
        results = [_result(50.0, 0.60), _result(45.0, 0.70), _result(45.0, 0.68)]
        results = [
            PipelineResult(
                claim=r.claim,
                score=r.score.model_copy(update={"score_low": r.score.score}),
                report_markdown="# test",
            )
            for r in results
        ]
        company = aggregate_claim_scores("X", _COMPANY_ID, results)
        assert company.score_low == 47.0  # 46.52, never rounded to 46.5 and then to 46

    def test_a_tie_for_third_goes_to_the_higher_confidence(self) -> None:
        results = [_result(60.0, 0.6), _result(50.0, 0.6), _result(38.0, 0.55), _result(38.0, 0.6)]
        company = aggregate_claim_scores("X", _COMPANY_ID, results)
        assert company.confidence == pytest.approx(0.6)

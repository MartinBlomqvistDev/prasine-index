"""Tests for the company-level aggregate: band helpers and worst-claim floor.

Pure-Python — no LLM calls, no network, no database.
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
        assert company.score_low >= 81.0

    def test_misleading_claim_floors_out_of_unverifiable(self) -> None:
        """H&M case: worst claim 52 (misleading) floors the aggregate at 41."""
        results = [_result(52.0), _result(33.0), _result(24.0), _result(22.0)]
        company = aggregate_claim_scores("H&M Group", _COMPANY_ID, results)
        assert company.score >= 41.0
        assert company.verdict == ScoreVerdict.MISLEADING_CLAIM
        assert company.floor_applied is True

    def test_no_floor_when_aggregate_already_in_band(self) -> None:
        """Ryanair case: all top claims confirmed — aggregate sits in band naturally."""
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

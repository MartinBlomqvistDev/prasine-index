"""Tests for the rules added after the run-4 review: national shares, pledge keys, the
forward-looking test for EUR-Lex records and the rounding of the company score."""

from __future__ import annotations

import uuid

import pytest

from agents.report_agent import published_evidence
from core.aggregate import aggregate_claim_scores
from ingest.eurlex import _forward_looking
from models.evidence import Evidence, EvidenceSource, EvidenceType
from tests.test_aggregate import _COMPANY_ID, _result, _stated
from tests.test_report_evidence import _score


def _national_for(country: str) -> Evidence:
    return Evidence(
        claim_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        source=EvidenceSource.EDGAR,
        evidence_type=EvidenceType.STATISTICAL,
        summary=f"EDGAR: {country} total.",
        raw_data={"type": "country_aggregate", "country": country},
        data_year=2024,
        supports_claim=None,
        confidence=0.8,
    )


class TestNationalShare:
    def test_ssab_wording_keeps_the_national_totals(self) -> None:
        record = _national_for("Sweden")
        claim = (
            "A significant reduction in Sweden's total CO2 emissions by 10% and Finland's by 7%."
        )
        assert published_evidence([record], _score([], []), claim) == [record]

    def test_a_claim_without_a_share_leaves_them_out(self) -> None:
        record = _national_for("Sweden")
        claim = "SSAB plans to make fossil-free steel in Sweden."
        assert published_evidence([record], _score([], []), claim) == []


class TestPledgeKeys:
    def test_different_scope_lists_are_different_pledges(self) -> None:
        results = [
            _stated(50.0, "Net zero across Scope 1, 2 and 3 emissions by 2040."),
            _stated(45.0, "Net zero for our Scope 1 and 2 emissions by 2040."),
            _result(30.0),
        ]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).pledges_counted_once == 0

    def test_a_scope_range_reads_as_its_scopes(self) -> None:
        results = [
            _stated(50.0, "Net zero across Scopes 1-3 by 2040."),
            _stated(45.0, "Net zero across Scope 1, 2 and 3 by 2040."),
            _result(30.0),
        ]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).pledges_counted_once == 1

    def test_a_base_year_does_not_split_the_same_pledge(self) -> None:
        results = [
            _stated(40.0, "Halve emissions by FY30 compared to a FY16 baseline."),
            _stated(38.0, "Halve emissions by 2030."),
            _result(30.0),
        ]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).pledges_counted_once == 1

    def test_production_is_not_products(self) -> None:
        results = [
            _stated(50.0, "Net zero in our production by 2050."),
            _stated(45.0, "Net zero for the products we sell by 2050."),
            _result(30.0),
        ]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).pledges_counted_once == 0


class TestForwardLooking:
    @pytest.mark.parametrize(
        "text",
        [
            "We will phase out these boilers by the end of 2026.",
            "Net zero by 2050.",
            "We commit to halve emissions.",
        ],
    )
    def test_forward_looking(self, text: str) -> None:
        assert _forward_looking(text)

    def test_a_past_result_is_not(self) -> None:
        assert not _forward_looking("In 2024 we cut emissions by 12%.")


class TestRounding:
    def test_an_exact_half_rounds_up(self) -> None:
        results = [_result(41.0, 0.60), _result(42.0, 0.75), _result(47.0, 0.75)]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).score == 44.0

    def test_confidence_is_a_whole_percent(self) -> None:
        results = [_result(50.0, 0.55), _result(45.0, 0.60), _result(40.0, 0.68)]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).confidence == 0.61


class TestPledgeGroups:
    IKEA_1 = (
        "We are committed to the Paris Agreement and to contribute to limiting the global "
        "temperature rise to 1.5\u00b0C above pre-industrial levels. This includes a commitment "
        "to reducing absolute greenhouse gas (GHG) emissions from the value chain by at least "
        "50% by FY30, compared to a FY16 baseline, and to reach net-zero emissions by FY50, "
        "without using carbon offsets to meet this absolute reduction target. In addition, we "
        "will remove and store carbon through forestry, agriculture and products in our value "
        "chain, along with contributing to additional reductions in society by going beyond "
        "our value chain."
    )
    IKEA_2 = (
        "We are dedicated to reduce our greenhouse gas emissions by 50% by 2030 and to reach "
        "net zero emissions by 2050."
    )

    def test_ikea_states_one_pledge_twice(self) -> None:
        results = [_stated(40.0, self.IKEA_1), _stated(38.0, self.IKEA_2), _result(30.0)]
        assert aggregate_claim_scores("IKEA", _COMPANY_ID, results).pledges_counted_once == 1

    def test_the_oxford_comma_keeps_scope_3(self) -> None:
        results = [
            _stated(50.0, "Net zero across Scope 1, 2, and 3 emissions by 2040."),
            _stated(45.0, "Net zero for our Scope 1 and 2 emissions by 2040."),
            _result(30.0),
        ]
        assert aggregate_claim_scores("X", _COMPANY_ID, results).pledges_counted_once == 0

    def test_an_unscoped_pledge_stays_apart_from_two_scoped_ones(self) -> None:
        results = [
            _stated(66.0, "Net zero across our operations by 2050."),
            _stated(64.0, "Net zero for the products we sell by 2050."),
            _stated(60.0, "We aim to be a net zero company by 2050."),
        ]
        assert aggregate_claim_scores("BP", _COMPANY_ID, results).pledges_counted_once == 0

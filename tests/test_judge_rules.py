"""Tests for the band rules the judge's score is held to.

The judge reports which records contradict a claim, which decisions found the
same claim misleading, and what a top-band score rests on;
:py:func:`agents.judge_agent.score_cap` then applies the rules in code. These
tests pin the failures found in November 2026 and the rule that replaced them:
a company-level rating cannot lift an ordinary claim, but the records that
measure a climate pledge's integrity count against the pledge.
"""

from __future__ import annotations

import uuid
from typing import Any

from agents.judge_agent import score_cap
from core.evidence_scope import can_be_pledge, record_scope
from models.claim import Claim, ClaimCategory, SourceType
from models.evidence import Evidence, EvidenceSource, EvidenceType


def _evidence(source: EvidenceSource, evidence_type: EvidenceType, **raw: Any) -> Evidence:
    return Evidence(
        claim_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        source=source,
        evidence_type=evidence_type,
        source_url="https://example.org/record",
        raw_data=raw,
        summary="A record.",
        data_year=2025,
        supports_claim=None,
        confidence=0.9,
    )


def _claim(text: str, category: ClaimCategory) -> Claim:
    return Claim(
        trace_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        source_url="https://example.com/claims",
        source_type=SourceType.WEBSITE,
        raw_text=text,
        claim_category=category,
    )


EU_ETS = _evidence(EvidenceSource.EU_ETS, EvidenceType.VERIFIED_EMISSIONS)
LOBBY_MAP = _evidence(EvidenceSource.LOBBY_MAP, EvidenceType.LOBBYING_RECORD)
SOURCE_DOCUMENT = _evidence(EvidenceSource.SOURCE_DOCUMENT, EvidenceType.SELF_REPORTED_EMISSIONS)
RECENT_FINDING = _evidence(
    EvidenceSource.ENFORCEMENT,
    EvidenceType.ENFORCEMENT_RULING,
    ruling_type="BANNED",
    decision_date="2024-04-09",
)
OLD_FINDING = _evidence(
    EvidenceSource.ENFORCEMENT,
    EvidenceType.ENFORCEMENT_RULING,
    ruling_type="BANNED",
    decision_date="2020-02-05",
)
COMMITMENTS = _evidence(
    EvidenceSource.ENFORCEMENT,
    EvidenceType.ENFORCEMENT_RULING,
    ruling_type="COMMITMENTS",
    decision_date="2025-11-06",
)
EVIDENCE = [EU_ETS, LOBBY_MAP, SOURCE_DOCUMENT, RECENT_FINDING, OLD_FINDING, COMMITMENTS]

PLEDGE = _claim("We will reach net zero by 2050.", ClaimCategory.NET_ZERO_TARGET)
PRODUCT = _claim("Our new packaging is fully recyclable.", ClaimCategory.CIRCULAR_ECONOMY)


def _cap(claim: Claim, **verdict: Any) -> float:
    return score_cap(verdict, EVIDENCE, claim)[0]


class TestPledges:
    def test_paris_wording_makes_a_pledge(self) -> None:
        claim = _claim("Our strategy is aligned with the Paris Agreement.", ClaimCategory.OTHER)
        assert can_be_pledge(claim)
        assert not can_be_pledge(PRODUCT)

    def test_lobbying_counts_against_a_pledge(self) -> None:
        verdict = {"contradicting_evidence": [2], "claim_is_pledge": True}
        assert _cap(PLEDGE, top_band_basis="NONE", **verdict) == 80.0

    def test_lobbying_is_context_when_the_judge_finds_no_pledge(self) -> None:
        verdict = {"contradicting_evidence": [2], "claim_is_pledge": False}
        assert _cap(PLEDGE, top_band_basis="NONE", **verdict) == 60.0

    def test_the_judge_cannot_make_any_claim_a_pledge(self) -> None:
        verdict = {"contradicting_evidence": [2], "claim_is_pledge": True}
        assert _cap(PRODUCT, top_band_basis="NONE", **verdict) == 60.0

    def test_lobbying_is_context_for_another_claim(self) -> None:
        assert _cap(PRODUCT, contradicting_evidence=[2], top_band_basis="NONE") == 60.0

    def test_lobbying_never_opens_the_top_band(self) -> None:
        verdict = {
            "contradicting_evidence": [2],
            "claim_is_pledge": True,
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [2],
        }
        assert _cap(PLEDGE, **verdict) == 80.0


class TestDecisions:
    def test_recent_finding_on_the_same_claim_counts(self) -> None:
        verdict = {"contradicting_evidence": [], "same_claim_decisions": [4]}
        assert _cap(PRODUCT, top_band_basis="NONE", **verdict) == 80.0

    def test_finding_older_than_five_years_does_not(self) -> None:
        verdict = {"contradicting_evidence": [], "same_claim_decisions": [5]}
        assert _cap(PRODUCT, top_band_basis="NONE", **verdict) == 60.0

    def test_commitments_are_not_a_finding(self) -> None:
        verdict = {"contradicting_evidence": [6], "same_claim_decisions": [6]}
        assert _cap(PRODUCT, top_band_basis="NONE", **verdict) == 60.0

    def test_a_finding_not_named_as_the_same_claim_is_context(self) -> None:
        assert _cap(PRODUCT, contradicting_evidence=[4], top_band_basis="NONE") == 60.0


class TestTopBand:
    def test_claim_level_contradiction_without_basis_stops_at_80(self) -> None:
        assert _cap(PRODUCT, contradicting_evidence=[3], top_band_basis="NONE") == 80.0

    def test_official_record_opens_the_top_band(self) -> None:
        verdict = {
            "contradicting_evidence": [1],
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [1],
        }
        assert _cap(PRODUCT, **verdict) == 100.0

    def test_the_company_document_cannot_be_the_official_record(self) -> None:
        verdict = {
            "contradicting_evidence": [3],
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [3],
        }
        assert _cap(PRODUCT, **verdict) == 80.0

    def test_invalid_record_numbers_are_ignored(self) -> None:
        verdict = {"contradicting_evidence": [0, 99, True, "1"], "top_band_basis": "NONE"}
        assert _cap(PRODUCT, **verdict) == 60.0


class TestRecordScope:
    def test_labels(self) -> None:
        assert record_scope(EU_ETS) == "claim-level"
        assert record_scope(LOBBY_MAP, PRODUCT) == "company-level"
        assert record_scope(LOBBY_MAP, PLEDGE).startswith("integrity criterion")
        assert record_scope(OLD_FINDING) == "enforcement record, context (BANNED)"
        assert record_scope(RECENT_FINDING).startswith("enforcement finding")

"""Tests for the band rules the judge's score is held to.

The judge reports which records contradict a claim and what a top-band score
rests on; :py:func:`agents.judge_agent.score_cap` then applies the rules in
code. These tests pin the two failures found in November 2026: a company-level
rating lifting every claim into the top band, and an enforcement decision about
another claim being treated as a finding against the claim under assessment.
"""

from __future__ import annotations

import uuid
from typing import Any

from agents.judge_agent import score_cap
from core.evidence_scope import record_scope
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


EU_ETS = _evidence(EvidenceSource.EU_ETS, EvidenceType.VERIFIED_EMISSIONS)
LOBBY_MAP = _evidence(EvidenceSource.LOBBY_MAP, EvidenceType.LOBBYING_RECORD)
SOURCE_DOCUMENT = _evidence(EvidenceSource.SOURCE_DOCUMENT, EvidenceType.SELF_REPORTED_EMISSIONS)
BAN = _evidence(
    EvidenceSource.ENFORCEMENT,
    EvidenceType.ENFORCEMENT_RULING,
    ruling_type="BANNED",
    decision_date="2024-04-09",
)
COMMITMENTS = _evidence(
    EvidenceSource.ENFORCEMENT,
    EvidenceType.ENFORCEMENT_RULING,
    ruling_type="COMMITMENTS",
    decision_date="2025-11-06",
)
EVIDENCE = [EU_ETS, LOBBY_MAP, SOURCE_DOCUMENT, BAN, COMMITMENTS]


def _cap(**verdict: Any) -> float:
    return score_cap(verdict, EVIDENCE)[0]


class TestCompanyLevelCap:
    def test_company_level_record_alone_cannot_pass_60(self) -> None:
        assert _cap(contradicting_evidence=[2], top_band_basis="NONE") == 60.0

    def test_enforcement_decision_alone_cannot_pass_60(self) -> None:
        verdict = {
            "contradicting_evidence": [4],
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [4],
        }
        assert _cap(**verdict) == 60.0

    def test_commitments_are_not_a_finding(self) -> None:
        assert _cap(contradicting_evidence=[5], top_band_basis="NONE") == 60.0

    def test_no_contradicting_records(self) -> None:
        assert _cap(contradicting_evidence=[], top_band_basis="NONE") == 60.0

    def test_invalid_record_numbers_are_ignored(self) -> None:
        assert _cap(contradicting_evidence=[0, 99, True, "1"], top_band_basis="NONE") == 60.0


class TestTopBand:
    def test_claim_level_contradiction_without_basis_stops_at_80(self) -> None:
        assert _cap(contradicting_evidence=[3], top_band_basis="NONE") == 80.0

    def test_official_record_opens_the_top_band(self) -> None:
        verdict = {
            "contradicting_evidence": [1],
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [1],
        }
        assert _cap(**verdict) == 100.0

    def test_the_company_document_cannot_be_the_official_record(self) -> None:
        verdict = {
            "contradicting_evidence": [3],
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [3],
        }
        assert _cap(**verdict) == 80.0

    def test_a_rating_cannot_be_the_official_record(self) -> None:
        verdict = {
            "contradicting_evidence": [1],
            "top_band_basis": "OFFICIAL_RECORD",
            "top_band_evidence": [2],
        }
        assert _cap(**verdict) == 80.0


class TestRecordScope:
    def test_labels(self) -> None:
        assert record_scope(EU_ETS) == "claim-level"
        assert record_scope(LOBBY_MAP) == "company-level"
        assert record_scope(BAN) == "enforcement record, context (BANNED)"

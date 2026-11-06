"""Tests for the verified enforcement records and the evidence built from them.

Each record is published as a statement about a named company, so these tests
pin what makes a record citable (a verbatim quote and the official page) and
the records for the index companies that were corrected in November 2026.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from types import SimpleNamespace

import pytest

from ingest.enforcement import _OUTCOME_TEXT, _RULING_TYPES, _validate, fetch_enforcement_data
from ingest.enforcement_records import RULINGS
from models.claim import Claim, ClaimCategory, SourceType
from models.evidence import Evidence


def _claim() -> Claim:
    return Claim(
        trace_id=uuid.uuid4(),
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        source_url="https://example.com/sustainability",
        source_type=SourceType.WEBSITE,
        raw_text="We will reach net zero by 2050.",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
    )


def _evidence_for(name: str) -> list[Evidence]:
    company = SimpleNamespace(name=name)
    return asyncio.run(fetch_enforcement_data(claim=_claim(), company=company))


def _references(name: str) -> dict[str, str]:
    return {e.raw_data["case_reference"]: e.raw_data["ruling_type"] for e in _evidence_for(name)}


class TestRecords:
    def test_every_record_is_citable(self) -> None:
        for r in RULINGS:
            assert r.quote.strip(), r.case_reference
            assert r.source_url.startswith("https://"), r.case_reference

    def test_every_outcome_has_a_description(self) -> None:
        assert set(_OUTCOME_TEXT) == _RULING_TYPES

    def test_validation_rejects_a_record_without_a_quote(self) -> None:
        broken = dataclasses.replace(RULINGS[0], quote=" ")
        with pytest.raises(ValueError, match="no verbatim quote"):
            _validate((broken,))

    def test_validation_rejects_an_unknown_outcome(self) -> None:
        broken = dataclasses.replace(RULINGS[0], ruling_type="GREENWASHING")
        with pytest.raises(ValueError, match="unknown outcome"):
            _validate((broken,))


class TestIndexCompanies:
    def test_ryanair(self) -> None:
        assert _references("Ryanair Holdings plc") == {
            "G19-1035778": "BANNED",
            "IP/25/2608": "COMMITMENTS",
        }

    def test_bp_has_only_a_complaint_that_was_not_upheld(self) -> None:
        evidence = _evidence_for("BP plc")
        assert _references("BP plc") == {"G16-1014902": "NOT_UPHELD"}
        assert "not upheld" in evidence[0].summary

    def test_hm(self) -> None:
        assert _references("H&M Group") == {
            "annual report 2019": "INVESTIGATION",
            "22/5262-1": "WARNING",
            "ACM/22/179209 (Document no. ACM/UIT/583382)": "COMMITMENTS",
        }

    def test_ikea(self) -> None:
        assert _references("IKEA Group") == {}  # Inter IKEA only; the decision concerns Ingka
        assert _references("Ingka Group") == {"2201-14": "CONFIRMED_MISLEADING"}

    @pytest.mark.parametrize("name", ["Glencore plc", "Enel SpA", "SSAB AB", "Ørsted A/S"])
    def test_companies_without_records(self, name: str) -> None:
        assert _evidence_for(name) == []


class TestEvidence:
    def test_summary_quotes_the_source_and_takes_no_side(self) -> None:
        evidence = _evidence_for("H&M Group")
        assert evidence
        for e in evidence:
            assert e.raw_data["quote"] in e.summary
            assert e.supports_claim is None
            assert e.source_url.startswith("https://")

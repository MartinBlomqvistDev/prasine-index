"""Tests for the company record set beside a company's claim findings.

The record is built in code from a run's evidence and states what each source
says. These tests pin the two integrity criteria it counts and the emissions
comparison, which must not read an installation joining the scheme as a rise.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.company_record import render_company_record
from models.evidence import Evidence, EvidenceSource, EvidenceType


def _evidence(source: EvidenceSource, summary: str = "A record.", **raw: Any) -> Evidence:
    return Evidence(
        claim_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        source=source,
        evidence_type=EvidenceType.VERIFIED_EMISSIONS,
        source_url="https://example.org/record",
        raw_data=raw,
        summary=summary,
        data_year=2025,
        supports_claim=None,
        confidence=0.9,
    )


def _ets(*rows: tuple[int, float]) -> Evidence:
    history = [{"year": year, "verifiedEmissions": value} for year, value in rows]
    return _evidence(EvidenceSource.EU_ETS, f"ETS {rows}", verified_emissions=history)


class TestIntegrityCriteria:
    def test_obstructive_lobbying_and_expansion_are_both_counted(self) -> None:
        record = render_company_record(
            [
                _evidence(EvidenceSource.LOBBY_MAP, performance_band="D+", year=2025),
                _evidence(EvidenceSource.COAL_EXIT, mining_expansion="yes", power_expansion=""),
            ]
        )
        assert "The records show 2 of the 2 conducts" in record
        assert "LobbyMap band D+ (2025), in LobbyMap's obstructive range" in record

    def test_missing_records_are_named_and_not_counted(self) -> None:
        record = render_company_record([])
        assert "neither of the 2 conducts" in record
        assert "No record for: lobbying and new fossil fuel supply." in record

    def test_repeated_records_from_several_claims_count_once(self) -> None:
        lobbying = [_evidence(EvidenceSource.LOBBY_MAP, performance_band="B") for _ in range(3)]
        record = render_company_record(lobbying)
        assert record.count("LobbyMap band B") == 1
        assert "outside LobbyMap's obstructive range" in record


class TestEmissions:
    def test_compares_only_years_every_installation_reported(self) -> None:
        record = render_company_record(
            [_ets((2013, 6e6), (2025, 12e6)), _ets((2021, 0.1e6), (2025, 0.1e6))]
        )
        assert "12.10 Mt CO2e in 2025" in record
        assert "against" not in record

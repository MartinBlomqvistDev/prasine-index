"""Tests for the company record set beside a company's claim findings.

The record is built in code from a run's evidence and states what each source
says. These tests pin how it reads two of the practices the UN expert group names,
and the emissions lines, which must not read an installation joining the scheme
as a change in emissions.
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


class TestPractices:
    def test_obstructive_lobbying_and_expansion(self) -> None:
        record = render_company_record(
            [
                _evidence(EvidenceSource.LOBBY_MAP, performance_band="D", year=2025),
                _evidence(EvidenceSource.COAL_EXIT, mining_expansion="yes", power_expansion=""),
            ]
        )
        assert "On the first, the Global Coal Exit List records new fossil fuel supply." in record
        assert (
            "LobbyMap rates the company's climate policy engagement D, within the range it defines as obstructive"
            in record
        )
        assert "Global Coal Exit List: listed as expanding (https://example.org/record)." in record

    def test_a_company_not_on_the_lists(self) -> None:
        record = render_company_record([])
        assert "nor the asset trackers record it as expanding supply" in record
        assert "LobbyMap has no rating for the company" in record

    def test_d_plus_is_outside_lobbymaps_obstructive_range(self) -> None:
        record = render_company_record([_evidence(EvidenceSource.LOBBY_MAP, performance_band="D+")])
        assert "D+, outside the range it defines as obstructive" in record

    def test_repeated_records_from_several_claims_count_once(self) -> None:
        lobbying = [_evidence(EvidenceSource.LOBBY_MAP, performance_band="B") for _ in range(3)]
        record = render_company_record(lobbying)
        assert record.count("LobbyMap band B") == 1
        assert "outside the range it defines as obstructive" in record


class TestTrackRecord:
    def test_an_old_finding_and_commitments(self) -> None:
        record = render_company_record(
            [
                _evidence(
                    EvidenceSource.ENFORCEMENT,
                    "ASA",
                    authority="ASA",
                    case_reference="G19-1035778",
                    decision_date="2020-02-05",
                    ruling_type="BANNED",
                ),
                _evidence(
                    EvidenceSource.ENFORCEMENT,
                    "CPC",
                    authority="European Commission and CPC network",
                    case_reference="IP/25/2608",
                    decision_date="2025-11-06",
                    ruling_type="COMMITMENTS",
                ),
            ]
        )
        assert (
            "**Track record in Prasine's list: one finding against its environmental "
            "marketing, more than five years old.**" in record
        )
        assert record.index("IP/25/2608") < record.index("G19-1035778")

    def test_a_complaint_that_was_not_upheld_is_no_finding(self) -> None:
        record = render_company_record(
            [
                _evidence(
                    EvidenceSource.ENFORCEMENT,
                    authority="ASA",
                    case_reference="G16-1014902",
                    decision_date="2019-10-02",
                    ruling_type="NOT_UPHELD",
                )
            ]
        )
        assert (
            "**Track record in Prasine's list: no findings against its environmental marketing.**"
            in record
        )
        assert ": not upheld" in record

    def test_no_records(self) -> None:
        assert "**Track record in Prasine's list: no decisions.**" in render_company_record([])


class TestEmissions:
    def test_only_years_every_installation_reported(self) -> None:
        record = render_company_record(
            [
                _ets((2013, 6e6), (2023, 10e6), (2024, 11e6), (2025, 12e6)),
                _ets((2021, 0.1e6), (2023, 0.1e6), (2024, 0.1e6), (2025, 0.1e6)),
            ]
        )
        assert "12.10 Mt CO2e in 2025; 11.10 Mt CO2e in 2024; 10.10 Mt CO2e in 2023." in record
        assert "2013" not in record and "2021" not in record


class TestLobbyingIntensity:
    """The engagement intensity is read from the file and described in LobbyMap's terms."""

    def test_intensity_described(self) -> None:
        from ingest.lobby_map import engagement_text

        assert "highly active or strategic engagement (above 25)" in engagement_text("45")
        assert "active engagement (above 12)" in engagement_text("19")
        assert "relatively limited engagement (below 12)" in engagement_text("8")
        assert engagement_text("") == ""
        assert engagement_text(None) == ""

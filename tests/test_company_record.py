"""Tests for the company record set beside a company's claim findings.

The record is built in code from a run's evidence and states what each source
says. These tests pin how it reads two of the practices the UN expert group names,
and the emissions lines, which must not read an installation joining the scheme
as a change in emissions, and must say when a comparison sum was taken before a
step in a series.
"""

from __future__ import annotations

import uuid
from typing import Any

from core.company_record import _emissions, render_company_record
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


def _installation(installation_id: str, series: dict[int, float]) -> Evidence:
    history = [{"year": year, "verifiedEmissions": value} for year, value in series.items()]
    return _evidence(
        EvidenceSource.EU_ETS,
        f"ETS {installation_id}",
        installation_id=installation_id,
        verified_emissions=history,
    )


_COAL_POWER = (
    "coal power expansion, which the expert group's recommendations for businesses include "
    "ending (Integrity Matters, p. 24)"
)


class TestPractices:
    def test_obstructive_lobbying_and_expansion(self) -> None:
        record = render_company_record(
            [
                _evidence(EvidenceSource.LOBBY_MAP, performance_band="D", year=2025),
                _evidence(EvidenceSource.COAL_EXIT, mining_expansion="yes", power_expansion=""),
            ]
        )
        assert (
            "On the first, the Global Coal Exit List records coal mining expansion, which is new "
            "fossil fuel supply." in record
        )
        assert (
            "LobbyMap rates the company's climate policy engagement D, within the range it defines as obstructive"
            in record
        )
        assert (
            "Global Coal Exit List: listed for coal mining expansion (https://example.org/record)."
            in record
        )

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
        assert "within the range it describes as broad support" in record

    def test_a_middle_band_is_outside_both_ranges(self) -> None:
        record = render_company_record([_evidence(EvidenceSource.LOBBY_MAP, performance_band="C")])
        assert "outside the range it defines as obstructive" in record


class TestFossilSupply:
    """Upstream and mining expansion are new supply; coal power expansion is named apart."""

    def test_one_list_with_coal_mining_and_coal_power(self) -> None:
        record = render_company_record(
            [_evidence(EvidenceSource.COAL_EXIT, mining_expansion="yes", power_expansion="yes")]
        )
        assert (
            "On the first, the Global Coal Exit List records coal mining expansion, which is new "
            f"fossil fuel supply, and {_COAL_POWER}." in record
        )
        assert "counting new coal plants" not in record
        assert (
            "Global Coal Exit List: listed for coal mining expansion and coal power expansion "
            "(https://example.org/record)." in record
        )

    def test_coal_mining_beside_coal_power_on_two_sources(self) -> None:
        record = render_company_record(
            [
                _evidence(EvidenceSource.COAL_EXIT, mining_expansion="yes", power_expansion="yes"),
                _evidence(EvidenceSource.GCPT, expanding_units=3),
            ]
        )
        assert (
            "On the first, the Global Coal Exit List records coal mining expansion, which is new "
            "fossil fuel supply, and the Global Coal Exit List and Global Coal Plant Tracker "
            f"record {_COAL_POWER}." in record
        )

    def test_coal_power_alone_is_no_new_supply(self) -> None:
        record = render_company_record([_evidence(EvidenceSource.GCPT, expanding_units=2)])
        assert (
            "On the first, no record shows new fossil fuel supply; the Global Coal Plant Tracker "
            f"records {_COAL_POWER}." in record
        )
        assert "Global Coal Plant Tracker: 2 units in development" in record

    def test_oil_and_gas_supply_beside_coal_power(self) -> None:
        record = render_company_record(
            [
                _evidence(EvidenceSource.GOGEL, upstream_expansion="yes", lng_expansion=""),
                _evidence(EvidenceSource.COAL_EXIT, mining_expansion="", power_expansion="yes"),
                _evidence(EvidenceSource.GCPT, expanding_units=1),
            ]
        )
        assert (
            "On the first, the Global Oil and Gas Exit List records new fossil fuel supply, and "
            "the Global Coal Exit List and Global Coal Plant Tracker record "
            f"{_COAL_POWER}." in record
        )
        assert "Global Oil and Gas Exit List: listed as expanding" in record
        assert "Global Coal Exit List: listed for coal power expansion" in record

    def test_a_long_stalled_proposal_is_not_counted(self) -> None:
        record = render_company_record(
            [
                _evidence(
                    EvidenceSource.EGT,
                    expanding=0,
                    stalled_assets=[{"name": "Example LNG Terminal", "proposal_year": 2007}],
                )
            ]
        )
        assert (
            "Europe Gas Tracker: 1 proposal still at the proposal stage more than ten years "
            "later, which is not counted as new supply: Example LNG Terminal (proposed in 2007)"
            in record
        )
        assert "On the first, no record shows new fossil fuel supply that counts;" in record


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
            "marketing, more than five years old, and one record of commitments to change "
            "it.**" in record
        )
        assert "no finding of a breach and no fine" in record
        assert record.index("IP/25/2608") < record.index("G19-1035778")

    def test_an_authoritys_own_outcome_and_kind_of_body(self) -> None:
        record = render_company_record(
            [
                _evidence(
                    EvidenceSource.ENFORCEMENT,
                    "RO",
                    authority="Reklamombudsmannen",
                    body="Sweden's advertising self-regulator",
                    case_reference="2201-14",
                    decision_date="2022-06-15",
                    ruling_type="CONFIRMED_MISLEADING",
                    outcome="",
                ),
                _evidence(
                    EvidenceSource.ENFORCEMENT,
                    "NCA",
                    authority="Forbrukertilsynet",
                    party_as_named="Hennes & Mauritz",
                    case_reference="2019/1144",
                    decision_date="2019-06-03",
                    ruling_type="INVESTIGATION",
                    outcome="case opened on 3 June 2019 and closed on 19 August 2019",
                ),
            ]
        )
        assert "Reklamombudsmannen (Sweden's advertising self-regulator) 2201-14" in record
        assert (
            "2019/1144 (2019-06-03), Hennes & Mauritz: case opened on 3 June 2019 and closed"
            in record
        )

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

    def test_says_the_mapped_installations_may_not_be_all(self) -> None:
        line = _emissions([_installation("SE_1", {2023: 5.0, 2024: 5.0, 2025: 5.0})])
        assert line.startswith(
            "EU ETS verified emissions for 1 installation mapped to the company by name, which "
            "may not be all of its installations: 5 t CO2e in 2025;"
        )
        history = [{"year": year, "verifiedEmissions": 5.0} for year in (2023, 2024, 2025)]
        operators = [
            _evidence(
                EvidenceSource.EU_ETS,
                f"ETS IE_{n}",
                installation_id=f"IE_{n}",
                aircraft_operator=True,
                verified_emissions=history,
            )
            for n in (1, 2)
        ]
        assert _emissions(operators).startswith(
            "EU ETS verified emissions for 2 aircraft operators mapped to the company by name, "
            "which may not be all of its aircraft operators: 10 t CO2e in 2025;"
        )


class TestComparisonSum:
    """A comparison sum taken before a step in a series says it is not like for like."""

    def test_steps_before_the_last_three_years(self) -> None:
        steady = dict.fromkeys(range(2015, 2026), 1000.0)
        # SE_495's series in the EU ETS, rounded to kilotonnes.
        stepped = {
            2015: 885.0,
            2016: 1511.0,
            2017: 1302.0,
            2018: 1058.0,
            2019: 1757.0,
            2020: 3063.0,
            2021: 3163.0,
            2022: 3135.0,
            2023: 3156.0,
            2024: 2842.0,
            2025: 2883.0,
        }
        line = _emissions([_installation("SE_494", steady), _installation("SE_495", stepped)])
        assert (
            "For comparison, 1,885 t CO2e in 2015; that sum includes SE_495 before the steps of "
            "more than half in its series described below, so it is not a like-for-like "
            "comparison with 2023 to 2025. The series change by more than half for SE_495 "
            "between 2015 and 2016 and between 2018 and 2019 and between 2019 and 2022:"
        ) in line

    def test_one_step_into_the_last_three_years(self) -> None:
        line = _emissions(
            [
                _installation("IE_1", {2022: 60.0, 2023: 100.0, 2024: 120.0, 2025: 110.0}),
                _installation("IE_2", {2022: 9000.0, 2023: 10000.0, 2024: 12000.0, 2025: 12300.0}),
            ]
        )
        assert (
            "For comparison, 9,060 t CO2e in 2022; that sum includes IE_1 before the step of "
            "more than half in its series described below, so it is not a like-for-like "
            "comparison with 2023 to 2025." in line
        )

    def test_a_step_within_the_last_three_years_leaves_the_comparison(self) -> None:
        line = _emissions(
            [
                _installation("SE_1", {2015: 100.0, 2023: 50.0, 2024: 50.0, 2025: 50.0}),
                _installation("DE_2", {2015: 10.0, 2023: 10.0, 2024: 30.0, 2025: 30.0}),
            ]
        )
        assert "For comparison, 110 t CO2e in 2015. The series change" in line
        assert "like-for-like" not in line
        assert "DE_2 between 2023 and 2024" in line

    def test_more_than_three_installations_are_named_as_the_note_names_them(self) -> None:
        years = range(2015, 2026)
        late = _installation("W_1", {y: (10.0 if y < 2024 else 30.0) for y in years})
        early = [
            _installation(name, {y: (10.0 if y < 2016 else 30.0) for y in years})
            for name in ("A_1", "B_1", "C_1", "D_1")
        ]
        line = _emissions([late, *early])
        assert (
            "that sum includes A_1, B_1, C_1 and 1 more before the steps of more than half in "
            "their series described below" in line
        )
        assert (
            "The series change by more than half for A_1 between 2015 and 2016; B_1 between "
            "2015 and 2016; C_1 between 2015 and 2016; and 2 more:" in line
        )


class TestLobbyingIntensity:
    """The engagement intensity is read from the file and described in LobbyMap's terms."""

    def test_intensity_described(self) -> None:
        from ingest.lobby_map import engagement_text

        assert "highly active or strategic engagement (above 25)" in engagement_text("45")
        assert "active engagement (above 12)" in engagement_text("19")
        assert "relatively limited engagement (below 12)" in engagement_text("8")
        assert engagement_text("") == ""
        assert engagement_text(None) == ""

    def test_band_names_the_lobbymap_profile(self) -> None:
        from ingest.lobby_map import _build_summary, _LobbyMapRecord

        def record(company: str) -> _LobbyMapRecord:
            return _LobbyMapRecord(
                company=company,
                ticker=None,
                country="",
                sector="Retail",
                score="",
                performance_band="B",
                active_engagement="51",
                year=None,
                retrieved="2026-11-05",
            )

        assert _build_summary("IKEA Group", record("IKEA")).startswith(
            "LobbyMap performance band for IKEA: B (scores as published on lobbymap.org"
        )
        assert _build_summary("IKEA Group", record("")).startswith(
            "LobbyMap performance band for IKEA Group: B"
        )

"""Tests for how the Europe Gas Tracker workbook is read and described.

Pure-Python: no LLM, no network. The workbook is built with the sheet and column
names of the real file (Europe-Gas-Tracker-2026-03-02.xlsx).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import openpyxl
import pytest

import ingest.egt as egt


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    pipelines = workbook.create_sheet("Gas Pipelines")
    pipelines.append(
        ["PipelineName", "SegmentName", "Status", "CountriesOrAreas", "Owner", "Parent"]
    )
    pipelines.append(
        ["Statpipe Gas Pipeline", "", "operating", "Norway", "", "Enel SpA [unknown %]"]
    )
    terminals = workbook.create_sheet("LNG Terminals")
    terminals.append(
        [
            "TerminalName",
            "UnitName",
            "FacilityType",
            "Status",
            "Country/Area",
            "Owner",
            "Parent",
            "Capacity",
            "CapacityUnits",
            "ProposalYear",
            "CapacityinMtpa",
        ]
    )
    terminals.append(
        [
            "Porto Empedocle LNG Terminal",
            "",
            "Import",
            "proposed",
            "Italy",
            "Nuove Energie [100%]",
            "Enel SpA [100.00%]",
            8,
            "bcm/y",
            2007,
            5.88,
        ]
    )
    plants = workbook.create_sheet("Oil & Gas Plants")
    plants.append(
        [
            "Country/Area",
            "Plant name",
            "Unit name",
            "Fuel",
            "Capacity (MW)",
            "Status",
            "Owner(s)",
            "Parent(s)",
        ]
    )
    plants.append(
        [
            "Italy",
            "Andrea Palladio power station",
            1.0,
            "fossil gas: natural gas",
            860,
            "pre-construction",
            "Enel Produzione SpA [100%]",
            "Enel SpA [100.00%]",
        ]
    )
    plants.append(
        [
            "Italy",
            "Archimede power station",
            1.0,
            "fossil gas: natural gas",
            360,
            "operating",
            "Enel Produzione SpA [100%]",
            "Enel SpA [100.00%]",
        ]
    )
    path = tmp_path / "Europe-Gas-Tracker.xlsx"
    workbook.save(path)
    monkeypatch.setattr(egt, "_XLSX_PATH", path)
    monkeypatch.setattr(egt, "_assets", None)
    return path


def _evidence(company: str):
    claim = SimpleNamespace(id=uuid.uuid4(), trace_id=uuid.uuid4())
    return asyncio.run(egt.fetch_egt_data(claim, SimpleNamespace(name=company)))


class TestPlants:
    """Gas plants are matched through the sheet's "Owner(s)" and "Parent(s)" columns."""

    def test_plants_are_matched_with_unit_and_share(self, tracker) -> None:
        evidence = _evidence("Enel SpA")
        summary = evidence[0].summary
        assert (
            "4 assets (1 gas pipeline segment, 1 LNG terminal unit, 2 gas-fired power units)"
            in summary
        )
        assert "Archimede power station unit 1 (gas-fired power unit, 360 MW" in summary
        assert "Enel SpA's share 100%" in summary

    def test_power_units_in_development_are_not_supply(self, tracker) -> None:
        evidence = _evidence("Enel SpA")
        summary = evidence[0].summary
        assert evidence[0].raw_data["expanding_power"] == 1
        assert "Gas-fired power units in development, not counted as fossil fuel supply" in summary

    def test_a_proposal_more_than_ten_years_old_is_not_counted(self, tracker) -> None:
        evidence = _evidence("Enel SpA")
        summary = evidence[0].summary
        assert evidence[0].raw_data["expanding"] == 0
        assert evidence[0].raw_data["stalled"] == 1
        assert "Proposed more than 10 years ago and still not past the proposal stage" in summary
        assert (
            "Porto Empedocle LNG Terminal (LNG terminal unit, import terminal, 8 bcm/y, "
            "proposed in 2007" in summary
        )
        assert egt.stalled_lng("Enel SpA") == [("Porto Empedocle LNG Terminal", 2007, 5.88)]


class TestExitListLng:
    """The exit list's LNG expansion is not counted when it is the same stalled terminal."""

    def _record(self, upstream: str, details: str) -> SimpleNamespace:
        return SimpleNamespace(upstream_expansion=upstream, lng_expansion="yes", details=details)

    def test_matched_by_capacity(self, monkeypatch) -> None:
        import ingest.gogel as gogel

        monkeypatch.setattr(
            gogel, "stalled_lng", lambda _name: [("Porto Empedocle LNG Terminal", 2007, 5.88)]
        )
        note = gogel._stalled_lng_note(
            "Enel SpA", self._record("no", "GOGEL 2025; LNG capacity under development 5.88 Mtpa")
        )
        assert "Porto Empedocle LNG Terminal, proposed in 2007" in note

    def test_counted_when_larger_or_upstream(self, monkeypatch) -> None:
        import ingest.gogel as gogel

        monkeypatch.setattr(gogel, "stalled_lng", lambda _name: [("Terminal", 2007, 5.88)])
        larger = self._record("no", "LNG capacity under development 9.5 Mtpa")
        upstream = self._record("yes", "LNG capacity under development 5.88 Mtpa")
        assert gogel._stalled_lng_note("X", larger) == ""
        assert gogel._stalled_lng_note("X", upstream) == ""

    def test_a_share_the_tracker_does_not_give(self, tracker) -> None:
        summary = _evidence("Enel SpA")[0].summary
        assert (
            "Statpipe Gas Pipeline (gas pipeline segment, Norway, operating, the tracker gives no share"
            in summary
        )

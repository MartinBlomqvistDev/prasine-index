"""Tests for how E-PRTR releases are summed: each pollutant on its own, CO2 as reported.

Pure-Python: no network, no database.
"""

from __future__ import annotations

from ingest.eprtr import _co2_by_year, _EprtrRecord, _other_pollutants


def _release(facility: str, year: int, pollutant: str, kg: float) -> _EprtrRecord:
    return _EprtrRecord(
        facility_name=facility,
        parent_company=facility,
        country="IT",
        year=year,
        pollutant=pollutant,
        quantity_kg=kg,
        medium="AIR",
    )


class TestPollutants:
    def test_co2_is_not_summed_with_other_pollutants(self) -> None:
        records = [
            _release("Plant A", 2024, "Carbon dioxide (CO2)", 2_000_000_000),
            _release("Plant A", 2024, "Nitrogen oxides (NOX)", 1_000_000),
            _release("Plant B", 2024, "Carbon dioxide (CO2)", 500_000_000),
        ]
        assert _co2_by_year({2024: records}) == {2024: 2_500_000.0}
        assert _other_pollutants(records) == {"Nitrogen oxides (NOX)": 1_000.0}

    def test_co2_excluding_biomass_is_not_added_to_the_total(self) -> None:
        records = [
            _release("Plant A", 2024, "Carbon dioxide (CO2)", 1_000_000),
            _release("Plant A", 2024, "Carbon dioxide (CO2) excluding biomass", 3_000_000),
        ]
        assert _co2_by_year({2024: records}) == {2024: 1_000.0}
        assert _other_pollutants(records) == {}

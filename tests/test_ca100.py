"""Tests for how the Climate Action 100+ benchmark is read and described.

Pure-Python: no LLM, no network.
"""

from __future__ import annotations

from ingest.ca100 import _build_records, describe_indicators


def _row(**values: str) -> dict[str, str]:
    row = {
        "Company": "Glencore plc",
        "ISIN": "JE00B4T3BW64",
        "HQ Country": "Switzerland",
        "Sector": "Diversified Mining",
        "Net Zero Ambition Benchmark": "No",
        "Net Zero Ambition Benchmark Progress": "Decline in score",
        "Long-term Target": "Partial",
        "Long-term Target Progress": "No change in score",
        "Climate Policy Engagement": "Partial",
        "Climate Policy Engagement Progress": "Not Applicable",
        "Year": "2026",
        "Benchmark": "October 2026",
        "Assessment Page": "https://www.climateaction100.org/company-assessments/glencore-plc/",
    }
    row.update(values)
    return row


class TestRecords:
    """Each indicator the file scores is read, with any change since the last benchmark."""

    def test_reads_every_indicator_with_its_change(self) -> None:
        record = _build_records([_row()])[1]["glencore"]
        assert record.benchmark == "October 2026"
        assert record.page.endswith("/company-assessments/glencore-plc/")
        assert record.indicators == [
            {
                "indicator": "net zero by 2050 ambition",
                "score": "No",
                "change": "lower than in the previous benchmark",
            },
            {"indicator": "long-term target (2036 to 2050)", "score": "Partial", "change": ""},
            {"indicator": "climate policy engagement", "score": "Partial", "change": ""},
        ]
        assert record.nz_ambition_class == "NOT_ALIGNED"

    def test_an_older_file_links_the_benchmark_page(self) -> None:
        row = _row()
        del row["Benchmark"], row["Assessment Page"]
        record = _build_records([row])[1]["glencore"]
        assert record.benchmark == "2026"
        assert record.page == "https://www.climateaction100.org/net-zero-company-benchmark/"


class TestDescription:
    """The record states its benchmark and every score it has."""

    def test_states_the_benchmark_and_the_scores(self) -> None:
        record = _build_records([_row()])[1]["glencore"]
        text = describe_indicators({"benchmark": record.benchmark, "indicators": record.indicators})
        assert text == (
            "October 2026 benchmark: net zero by 2050 ambition No, lower than in the previous "
            "benchmark; long-term target (2036 to 2050) Partial; climate policy engagement "
            "Partial."
        )

    def test_a_record_without_scores_says_so(self) -> None:
        assert describe_indicators({"benchmark": "October 2026", "indicators": []}) == (
            "October 2026 benchmark: no indicator scores."
        )

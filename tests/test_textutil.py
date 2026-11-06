"""Tests for the shared HTML-to-text helpers and the pages-read note."""

from __future__ import annotations

from core.textutil import final_counters, html_to_text
from ingest.source_document import _strip_html, pages_read_note


class TestFinalCounters:
    def test_a_counter_reads_its_final_value(self) -> None:
        html = '<p>Down <span class="counter" data-final="38">1</span>%</p>'
        assert "38" in html_to_text(html)
        assert "Down 38 %" in _strip_html(html)

    def test_other_elements_are_untouched(self) -> None:
        html = '<span class="x">7</span>'
        assert final_counters(html) == html


class TestPagesReadNote:
    def test_names_the_pages_read_as_ranges(self) -> None:
        text = "[PDF page 104] a [PDF page 130] b [PDF page 131] c [PDF page 132] d"
        note = pages_read_note("https://x/report.pdf", text, 700)
        assert "a PDF of 700 pages" in note
        assert "PDF pages 104 and 130-132 were read" in note

    def test_says_nothing_when_every_page_was_read(self) -> None:
        assert pages_read_note("https://x/r.pdf", "[PDF page 1] a [PDF page 2] b", 2) == ""


class TestDisplayedName:
    def test_match_labels_name_the_company_as_the_report_does(self) -> None:
        import uuid

        from core.pipeline import as_displayed
        from models.evidence import Evidence, EvidenceSource, EvidenceType

        record = Evidence(
            claim_id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            source=EvidenceSource.SBTI,
            evidence_type=EvidenceType.STATISTICAL,
            source_url="https://sciencebasedtargets.org/target-dashboard",
            raw_data={},
            summary="SBTi register entry 'IKEA' (matched to IKEA Group): near-term targets.",
            supports_claim=None,
            confidence=0.9,
        )
        (shown,) = as_displayed([record], "IKEA Group", "IKEA (Inter IKEA Group)")
        assert "(matched to IKEA (Inter IKEA Group))" in shown.summary


class TestMethodNotePages:
    def test_the_note_after_a_figure_page_is_read(self) -> None:
        from ingest.source_document import select_pages

        pages = [
            "climate emissions target net zero " * 20,
            "Scope 3 emissions fell 23% against the baseline.",
            "Methodology: the reductions are calculated from supplier data.",
            "Unrelated page about stores.",
        ]
        text = select_pages(pages, 100_000, True, ("23%",))
        assert "[PDF page 3]" in text
        assert "[PDF page 4]" not in text


class TestEmissionsLine:
    def test_gives_a_longer_view_and_flags_a_break(self) -> None:
        import uuid

        from core.company_record import _emissions
        from models.evidence import Evidence, EvidenceSource, EvidenceType

        def record(installation: str, series: dict[int, float]) -> Evidence:
            return Evidence(
                claim_id=uuid.uuid4(),
                trace_id=uuid.uuid4(),
                source=EvidenceSource.EU_ETS,
                evidence_type=EvidenceType.VERIFIED_EMISSIONS,
                source_url="https://union-registry-data.ec.europa.eu/",
                raw_data={
                    "installation_id": installation,
                    "verified_emissions": [
                        {"year": y, "verifiedEmissions": v} for y, v in series.items()
                    ],
                },
                summary="EU ETS.",
                supports_claim=None,
                confidence=0.9,
            )

        line = _emissions(
            [
                record("SE_1", {2015: 100.0, 2023: 50.0, 2024: 50.0, 2025: 50.0}),
                record("DE_2", {2015: 10.0, 2023: 10.0, 2024: 30.0, 2025: 30.0}),
            ]
        )
        assert "2 mapped installations" in line
        assert "For comparison" in line and "in 2015" in line
        assert "DE_2 between 2023 and 2024" in line

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

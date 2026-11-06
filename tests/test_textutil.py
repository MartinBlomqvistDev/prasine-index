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

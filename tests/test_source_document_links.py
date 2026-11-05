"""Tests for how the source document step finds the report a claim page links to.

Pure-Python: no LLM, no network.
"""

from __future__ import annotations

from ingest.source_document import _linked_report


class TestLinkedReport:
    """The report a page links to is found by its address."""

    def test_finds_the_sustainability_report(self) -> None:
        html = (
            '<a href="/files/cookie-policy.pdf">Cookies</a>'
            '<a href="/wp-content/uploads/2026/07/Ryanair-FY26-Sustainability-Report.pdf">'
            "Download our FY26 Sustainability Report</a>"
        )
        assert (
            _linked_report(html, "https://corporate.ryanair.com/sustainability/")
            == "https://corporate.ryanair.com/wp-content/uploads/2026/07/"
            "Ryanair-FY26-Sustainability-Report.pdf"
        )

    def test_ignores_unrelated_pdfs(self) -> None:
        html = '<a href="/files/cookie-policy.pdf">Cookies</a><a href="/menu.pdf">Menu</a>'
        assert _linked_report(html, "https://example.com/") is None


class TestLocalCopies:
    """A registered local copy is read in place of the fetch, under its public address."""

    def test_copy_is_found_by_its_public_address(self, tmp_path) -> None:
        from core.local_copies import read_copy, register_copy

        copy = tmp_path / "annual-report.pdf"
        copy.write_bytes(b"%PDF-1.7 test")
        register_copy("https://example.com/report.pdf", copy)
        assert read_copy("https://example.com/report.pdf#page=4") == (
            "application/pdf",
            b"%PDF-1.7 test",
        )
        assert read_copy("https://example.com/other.pdf") is None

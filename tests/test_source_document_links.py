"""Tests for what the source document step reads besides the claim page.

Pure-Python: no LLM, no network.
"""

from __future__ import annotations

from ingest.source_document import (
    _choose_reports,
    _read_more_page,
    _report_links,
    climate_pages,
)

GLENCORE_CLIMATE = "https://www.glencore.com/sustainability/esg-a-z/climate-change"
RYANAIR = "https://corporate.ryanair.com/sustainability/"


class TestLinkedReports:
    """The documents a page links to are chosen by kind and by year."""

    def test_transition_plan_first_then_the_report(self) -> None:
        html = (
            '<a href="/docs/GLEN-2025-Sustainability-Report.pdf">2025 Sustainability Report</a>'
            '<a href="/docs/GLEN-2025-Annual-Report.pdf">2025 Annual Report</a>'
            '<a href="/docs/GLEN-2024-2026-Climate-Action-Transition-Plan.pdf">'
            "Download the 2024-2026 Climate Action Transition Plan</a>"
            '<a href="/docs/Scope+3+methodology.pdf">Scope 3 emissions calculation methodology</a>'
            '<a href="/docs/2025+Modern+Slavery+Statement.pdf">Modern Slavery Statement</a>'
        )
        assert _choose_reports(_report_links(html, GLENCORE_CLIMATE)) == [
            "https://www.glencore.com/docs/GLEN-2024-2026-Climate-Action-Transition-Plan.pdf",
            "https://www.glencore.com/docs/GLEN-2025-Sustainability-Report.pdf",
        ]

    def test_the_latest_report_of_a_kind_without_its_fragment(self) -> None:
        html = (
            '<a href="/wp-content/uploads/2026/07/Ryanair-FY26-Sustainability-Statement.pdf'
            '#page=79">Read more</a>'
            '<a href="/wp-content/uploads/2025/09/Ryanair-Sustainability-Report-2025.pdf">'
            "Download PDF</a>"
            '<a href="/wp-content/uploads/2021/12/2021-Sustainability-Report_Spreads.pdf">'
            "Download PDF</a>"
        )
        assert _choose_reports(_report_links(html, RYANAIR)) == [
            "https://corporate.ryanair.com/wp-content/uploads/2026/07/"
            "Ryanair-FY26-Sustainability-Statement.pdf"
        ]

    def test_an_old_report_of_another_kind_is_left_out(self) -> None:
        html = (
            '<a href="/files/annual-report-2025.pdf">Annual Report 2025</a>'
            '<a href="/files/climate-report-2019.pdf">Climate report 2019</a>'
        )
        assert _choose_reports(_report_links(html, "https://example.com/")) == [
            "https://example.com/files/annual-report-2025.pdf"
        ]

    def test_a_hex_identifier_is_not_a_year(self) -> None:
        html = '<a href="/static/a2031b9c/Sustainability-Report.pdf">Sustainability Report</a>'
        assert _report_links(html, "https://example.com/") == [
            (
                "sustainability report",
                "https://example.com/static/a2031b9c/Sustainability-Report.pdf",
                0,
            )
        ]

    def test_ignores_unrelated_pdfs(self) -> None:
        html = '<a href="/files/cookie-policy.pdf">Cookies</a><a href="/menu.pdf">Menu</a>'
        assert _choose_reports(_report_links(html, "https://example.com/")) == []


class TestReadMorePage:
    """A "Read more" link right after the claim is followed to the page it opens."""

    INDEX = (
        "<h3>Child labour</h3><p>We do not tolerate child labour.</p>"
        '<a href="/sustainability/esg-a-z/human-rights">Read more about child labour</a>'
        "<h3>Climate change</h3><p>We are committed to playing our part in the transition "
        "to a low-carbon economy. Our industrial emissions reduction targets are set "
        "against a 2019 baseline.</p>"
        '<a href="/sustainability/esg-a-z/climate-change">Read more about climate change</a>'
        "<h3>Communities</h3><p>We engage with communities.</p>"
        '<a href="/sustainability/esg-a-z/social-performance">Read more about communities</a>'
    )

    def test_follows_the_link_after_the_claim(self) -> None:
        claim = "Our industrial emissions reduction targets are set against a 2019 baseline."
        assert (
            _read_more_page(self.INDEX, "https://www.glencore.com/sustainability/esg-a-z", claim)
            == "https://www.glencore.com/sustainability/esg-a-z/climate-change"
        )

    def test_matches_across_quotes_and_entities(self) -> None:
        html = (
            "<p>We&rsquo;re cutting emissions by 27% by 2031.</p>"
            '<a href="/news/sbti">Learn more</a>'
        )
        claim = "We\u2019re cutting emissions by 27% by 2031."
        assert _read_more_page(html, "https://example.com/climate", claim) == (
            "https://example.com/news/sbti"
        )

    def test_a_pdf_or_another_site_is_not_followed(self) -> None:
        pdf = '<p>Net zero by 2050.</p><a href="/report.pdf#page=79">Read more</a>'
        other = '<p>Net zero by 2050.</p><a href="https://other.org/net-zero">Read more</a>'
        assert _read_more_page(pdf, "https://example.com/", "Net zero by 2050.") is None
        assert _read_more_page(other, "https://example.com/", "Net zero by 2050.") is None

    def test_no_link_when_the_claim_is_not_on_the_page(self) -> None:
        assert _read_more_page(self.INDEX, "https://www.glencore.com/", "Not here.") is None


class TestClimatePages:
    """An assurance report's pages are read first, then the pages about climate."""

    def _patch_pages(self, monkeypatch, texts: list[str]) -> None:
        import pypdf

        class _Page:
            def __init__(self, text: str) -> None:
                self._text = text

            def extract_text(self) -> str:
                return self._text

        class _Reader:
            def __init__(self, _stream) -> None:
                self.pages = [_Page(text) for text in texts]

        monkeypatch.setattr(pypdf, "PdfReader", _Reader)

    def test_assurance_pages_come_first(self, monkeypatch) -> None:
        climate = "Scope 1 emissions fell. Net zero by 2050. " * 40
        assurance = "Independent practitioner's limited assurance report on the statement."
        self._patch_pages(monkeypatch, [climate, climate, "Board report", assurance])
        text = climate_pages(b"%PDF", limit=len(climate) + len(assurance) + 10)
        assert "[page 4]" in text
        assert "[page 1]" in text
        assert "[page 2]" not in text

    def test_no_assurance_pages_for_claim_extraction(self, monkeypatch) -> None:
        climate = "Net zero by 2050. " * 10
        assurance = "limited assurance " * 20
        self._patch_pages(monkeypatch, [climate, assurance])
        assert "[page 2]" not in climate_pages(b"%PDF", assurance=False)

    def test_assurance_alone_is_not_a_climate_page(self, monkeypatch) -> None:
        self._patch_pages(monkeypatch, ["Board report", "limited assurance on the statement"])
        assert climate_pages(b"%PDF") == ""


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

"""Tests for the generated Evidence section of a published report.

The evidence list in a report is rendered from the verification records rather
than written by the model, so the published list always matches what the judge
saw and carries the support label the site reads. Pure-Python: no LLM, no
network, no database.
"""

from __future__ import annotations

import uuid

from agents.report_agent import _insert_evidence_section, render_evidence_section
from models.evidence import Evidence, EvidenceSource, EvidenceType


def _evidence(supports: bool | None, summary: str, url: str | None = None) -> Evidence:
    return Evidence(
        claim_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        source=EvidenceSource.EU_ETS,
        evidence_type=EvidenceType.VERIFIED_EMISSIONS,
        source_url=url,
        summary=summary,
        data_year=2025,
        supports_claim=supports,
        confidence=0.85,
    )


class TestRenderEvidenceSection:
    def test_numbers_records_and_labels_support(self) -> None:
        rendered = render_evidence_section(
            [
                _evidence(False, "Verified emissions rose.", "https://example.org/a"),
                _evidence(True, "Verified emissions fell."),
                _evidence(None, "Installation list."),
            ]
        )
        paragraphs = rendered.split("\n\n")
        assert paragraphs[0].startswith("**[1] EU ETS** Verified emissions rose. (2025).")
        assert "Supports claim: No." in paragraphs[0]
        assert paragraphs[0].endswith("(confidence 0.85) https://example.org/a")
        assert "Supports claim: Yes." in paragraphs[1]
        assert "Supports claim: Context." in paragraphs[2]

    def test_empty_evidence_says_so(self) -> None:
        assert render_evidence_section([]) == "No evidence records were returned."


class TestInsertEvidenceSection:
    def test_replaces_model_written_evidence(self) -> None:
        report = (
            '### The Claim\n> "x"\n\n### Evidence\nThe model invented a ruling here.\n\n'
            "### Assessment\nText.\n"
        )
        result = _insert_evidence_section(report, [_evidence(False, "Verified emissions rose.")])
        assert "invented a ruling" not in result
        assert "**[1] EU ETS** Verified emissions rose." in result
        assert result.index("### Evidence") < result.index("**[1]") < result.index("### Assessment")

    def test_adds_missing_section_before_assessment(self) -> None:
        report = '### The Claim\n> "x"\n\n### Assessment\nText.\n'
        result = _insert_evidence_section(report, [_evidence(True, "Verified emissions fell.")])
        assert result.index("### Evidence") < result.index("### Assessment")

"""Tests for the generated Evidence section of a published report.

The evidence list in a report is rendered from the verification records rather
than written by the model, so the published list always matches what the judge
saw, and each record is labelled by how the judge read it for this claim.
Pure-Python: no LLM, no network, no database.
"""

from __future__ import annotations

import uuid

from agents.report_agent import (
    _insert_evidence_section,
    published_evidence,
    render_evidence_section,
)
from models.evidence import Evidence, EvidenceSource, EvidenceType
from models.score import GreenwashingScore, ScoreVerdict


def _evidence(summary: str, url: str | None = None) -> Evidence:
    return Evidence(
        claim_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        source=EvidenceSource.EU_ETS,
        evidence_type=EvidenceType.VERIFIED_EMISSIONS,
        source_url=url,
        summary=summary,
        data_year=2025,
        supports_claim=None,
        confidence=0.85,
    )


def _score(contradicting: list[Evidence], supporting: list[Evidence]) -> GreenwashingScore:
    return GreenwashingScore(
        claim_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        score=70.0,
        verdict=ScoreVerdict.LIKELY_GREENWASHING,
        reasoning="Reasoning.",
        confidence=0.8,
        judge_model_id="claude-opus-5-5",
        contradicting_evidence_ids=[e.id for e in contradicting],
        supporting_evidence_ids=[e.id for e in supporting],
    )


class TestRenderEvidenceSection:
    def test_labels_follow_the_judge(self) -> None:
        rose = _evidence("Verified emissions rose.", "https://example.org/a")
        fell = _evidence("Verified emissions fell.")
        listing = _evidence("Installation list.")
        rendered = render_evidence_section([rose, fell, listing], _score([rose], [fell]))
        paragraphs = rendered.split("\n\n")
        assert paragraphs[0].startswith("**[1] EU ETS** Verified emissions rose. (2025).")
        assert "Supports claim: No." in paragraphs[0]
        assert paragraphs[0].endswith("(confidence 0.85) https://example.org/a")
        assert "Supports claim: Yes." in paragraphs[1]
        assert "Supports claim: Context." in paragraphs[2]

    def test_without_a_score_every_record_is_context(self) -> None:
        rendered = render_evidence_section([_evidence("Verified emissions rose.")])
        assert "Supports claim: Context." in rendered

    def test_empty_evidence_says_so(self) -> None:
        assert render_evidence_section([]) == "No evidence records were returned."


class TestInsertEvidenceSection:
    def test_replaces_model_written_evidence(self) -> None:
        report = (
            '### The Claim\n> "x"\n\n### Evidence\nThe model invented a ruling here.\n\n'
            "### Assessment\nText.\n"
        )
        result = _insert_evidence_section(report, [_evidence("Verified emissions rose.")])
        assert "invented a ruling" not in result
        assert "**[1] EU ETS** Verified emissions rose." in result
        assert result.index("### Evidence") < result.index("**[1]") < result.index("### Assessment")

    def test_adds_missing_section_before_assessment(self) -> None:
        report = '### The Claim\n> "x"\n\n### Assessment\nText.\n'
        result = _insert_evidence_section(report, [_evidence("Verified emissions fell.")])
        assert result.index("### Evidence") < result.index("### Assessment")


def _national(source: EvidenceSource) -> Evidence:
    return Evidence(
        claim_id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        source=source,
        evidence_type=EvidenceType.STATISTICAL,
        summary="National total.",
        raw_data={"type": "country_aggregate"},
        data_year=2024,
        supports_claim=None,
        confidence=0.8,
    )


class TestPublishedEvidence:
    """National totals stay out of a report unless the judge cited them."""

    def test_uncited_national_totals_are_left_out(self) -> None:
        company = _evidence("Company installations.")
        edgar = _national(EvidenceSource.EDGAR)
        trace = _national(EvidenceSource.CLIMATE_TRACE)
        kept = published_evidence([edgar, company, trace], _score([], []))
        assert kept == [company]

    def test_cited_national_total_is_kept(self) -> None:
        eea = _national(EvidenceSource.EEA_NATIONAL)
        kept = published_evidence([eea], _score([eea], []))
        assert kept == [eea]

    def test_a_claim_about_a_national_share_keeps_the_national_totals(self) -> None:
        edgar = _national(EvidenceSource.EDGAR)
        claim = "SSAB accounts for around 10 percent of Sweden's carbon dioxide emissions."
        assert published_evidence([edgar], _score([], []), claim) == [edgar]

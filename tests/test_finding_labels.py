"""Tests for the published names of the score bands.

Readers see a finding such as "Not fully supported", never the internal band
name. Reports generated before the labels changed are converted with the same
mapping, so the two must agree.
"""

from __future__ import annotations

from models.score import FINDING_LABELS, ScoreVerdict, finding_label, verdict_for_score


class TestFindingLabels:
    def test_every_band_has_a_label(self) -> None:
        assert set(FINDING_LABELS) == set(ScoreVerdict)

    def test_labels_follow_the_bands(self) -> None:
        assert finding_label(verdict_for_score(10)) == "Supported by records"
        assert finding_label(verdict_for_score(30)) == "Not checked against public records"
        assert finding_label(verdict_for_score(55)) == "Not fully supported"
        assert finding_label(verdict_for_score(70)) == "Conflicts with records"
        assert finding_label(verdict_for_score(90)) == "Contradicted by records"

    def test_no_label_names_a_legal_conclusion(self) -> None:
        for label in FINDING_LABELS.values():
            assert "greenwash" not in label.lower()
            assert "misleading" not in label.lower()

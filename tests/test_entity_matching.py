"""Tests for ingest entity matching — the highest legal-risk code in the repo.

A false-positive match against GCEL/GOGEL/enforcement data would publish an
untrue statement about a named company. These tests pin the name-normalisation
and lookup behaviour for the index companies. Pure-Python: the enforcement
database is static and the Transparency Register lookup is tested against an
injected cache — no data files, no network, no LLM.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

import ingest.eu_transparency_register as eu_tr
from ingest.enforcement import _normalise_name as enf_normalise
from ingest.enforcement import fetch_enforcement_data
from ingest.eu_transparency_register import _normalise_name as tr_normalise
from models.claim import Claim, ClaimCategory, SourceType

_COMPANY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _claim(text: str = "We will reach net zero by 2050.") -> Claim:
    return Claim(
        trace_id=uuid.uuid4(),
        company_id=_COMPANY_ID,
        source_url="https://example.com/sustainability",
        source_type=SourceType.WEBSITE,
        raw_text=text,
        claim_category=ClaimCategory.NET_ZERO_TARGET,
    )


class TestNormaliseName:
    """Both ingest modules strip legal suffixes the same way."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Ryanair Holdings plc", "ryanair"),
            ("BP plc", "bp"),
            ("Glencore plc", "glencore"),
            ("Enel SpA", "enel"),
            ("SSAB AB", "ssab"),
            ("Danone SA", "danone"),
            ("TotalEnergies SE", "totalenergies"),
            ("RWE AG", "rwe"),
            ("Securitas AB", "securitas"),
        ],
    )
    def test_index_companies(self, raw: str, expected: str) -> None:
        assert enf_normalise(raw) == expected
        assert tr_normalise(raw) == expected

    @pytest.mark.parametrize(
        "name",
        ["Vestas", "Atlas Copco", "Stegra", "Kappahl"],
    )
    def test_no_overstripping(self, name: str) -> None:
        """Names merely ENDING in suffix letters (no space) must not be cut."""
        assert enf_normalise(name) == name.lower()
        assert tr_normalise(name) == name.lower()


class TestEnforcementLookup:
    def test_ryanair_matches_known_rulings(self) -> None:
        company = SimpleNamespace(name="Ryanair Holdings plc")
        evidence = asyncio.run(fetch_enforcement_data(claim=_claim(), company=company))
        assert evidence, "Ryanair has documented ASA/EC enforcement records"
        summaries = " ".join(e.summary for e in evidence)
        assert "ASA" in summaries or "Commission" in summaries

    def test_unknown_company_returns_empty(self) -> None:
        company = SimpleNamespace(name="Gröna Fiktiva Energi AB")
        evidence = asyncio.run(fetch_enforcement_data(claim=_claim(), company=company))
        assert evidence == []

    def test_short_name_does_not_substring_match(self) -> None:
        """Names shorter than 5 chars must not fuzzy-match into other keys."""
        company = SimpleNamespace(name="Eon")  # norm 'eon' — inside 'exxon'? must not match
        evidence = asyncio.run(fetch_enforcement_data(claim=_claim(), company=company))
        for e in evidence:
            assert "eon" in e.summary.lower()


class TestTransparencyRegisterLookup:
    def _inject(self, names: dict[str, str]) -> None:
        cache = {}
        for raw_name, reg_number in names.items():
            record = eu_tr._TRRecord(
                reg_number=reg_number,
                name=raw_name,
                status="Activated",
                category="Companies & groups",
                country="SE",
            )
            cache[tr_normalise(raw_name)] = record
        eu_tr._cache_by_name = cache

    def teardown_method(self) -> None:
        eu_tr._cache_by_name = None  # restore lazy-load state

    def test_exact_match(self) -> None:
        self._inject({"H&M Hennes & Mauritz AB": "111-11"})
        result = eu_tr.lookup_registration("H&M Hennes & Mauritz AB")
        assert result is not None
        assert result["reg_number"] == "111-11"

    def test_substring_match_company_within_registrant(self) -> None:
        self._inject({"Ryanair Holdings plc": "222-22"})
        result = eu_tr.lookup_registration("Ryanair")
        assert result is not None
        assert result["reg_number"] == "222-22"

    def test_miss_returns_none_not_false_negative_claim(self) -> None:
        self._inject({"Ryanair Holdings plc": "222-22"})
        assert eu_tr.lookup_registration("Wizz Air Holdings plc") is None

    def test_export_available_reflects_cache(self) -> None:
        self._inject({"Enel SpA": "333-33"})
        assert eu_tr.register_export_available() is True

"""Tests for the EU law records that the judge and the reports are given.

The records are embedded in ingest/eurlex.py. These tests pin the passages that
quote the Commission services' Questions and Answers verbatim and the stated
scope of the EU ETS Directive record. No network, no LLM.
"""

from __future__ import annotations

import asyncio
import uuid

from ingest.eurlex import fetch_eurlex_data
from models.claim import Claim, ClaimCategory, SourceType
from models.evidence import Evidence


def _records(category: ClaimCategory, text: str) -> list[Evidence]:
    claim = Claim(
        trace_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        source_url="https://example.com/climate",
        source_type=SourceType.WEBSITE,
        raw_text=text,
        claim_category=category,
    )
    return asyncio.run(fetch_eurlex_data(claim=claim, company=None))


class TestOffsetting:
    def test_quotes_the_commission_answer_verbatim(self) -> None:
        records = _records(ClaimCategory.CARBON_NEUTRAL, "Our operations are carbon neutral.")
        (offsetting,) = [r for r in records if "point 4c" in r.summary]
        assert (
            '"The prohibition in Annex I point 4c does not apply to claims based on offsetting '
            "at company level, however such claims remain subject to other relevant provisions "
            'of the UCPD."' in offsetting.summary
        )


class TestEuEts:
    def test_states_what_the_verified_figures_cover(self) -> None:
        records = _records(ClaimCategory.EMISSIONS_REDUCTION, "Our emissions fell by 10% in 2024.")
        (ets,) = [r for r in records if r.raw_data["celex"] == "32003L0087"]
        assert (
            "They cover only the installations and aviation activities an operator has in the "
            "scheme." in ets.summary
        )
        assert "value chain" not in ets.summary

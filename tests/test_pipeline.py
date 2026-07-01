"""Integration tests for pipeline claim-filtering logic.

Tests cover the pure-Python functions that run before any LLM call:
deduplication, category diversity, and claim priority scoring.
No LLM calls, no network, no database.
"""

from __future__ import annotations

import uuid

import pytest

from core.pipeline import _claim_priority_score, _deduplicate_claims, _diversify_claims
from models.claim import Claim, ClaimCategory, SourceType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPANY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TRACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _claim(
    text: str,
    category: ClaimCategory = ClaimCategory.NET_ZERO_TARGET,
    normalised: str | None = None,
) -> Claim:
    """Build a minimal Claim with the given text and category."""
    return Claim(
        trace_id=_TRACE_ID,
        company_id=_COMPANY_ID,
        source_url="https://example.com/sustainability",
        source_type=SourceType.WEBSITE,
        raw_text=text,
        normalised_text=normalised,
        claim_category=category,
    )


# ---------------------------------------------------------------------------
# _deduplicate_claims
# ---------------------------------------------------------------------------


class TestDeduplicateClaims:
    def test_empty_list_returns_empty(self) -> None:
        assert _deduplicate_claims([]) == []

    def test_single_claim_passes_through(self) -> None:
        c = _claim("We will reach net zero by 2040.")
        result = _deduplicate_claims([c])
        assert len(result) == 1

    def test_exact_duplicate_keeps_one(self) -> None:
        text = "We will reach net zero by 2040."
        claims = [_claim(text), _claim(text)]
        result = _deduplicate_claims(claims)
        assert len(result) == 1

    def test_longer_version_is_kept(self) -> None:
        short = _claim("We will reach net zero by 2040.")
        long = _claim(
            "We will reach net zero across Scope 1, 2, and 3 by 2040 "
            "in line with the Science Based Targets initiative pathway."
        )
        result = _deduplicate_claims([short, long])
        assert len(result) == 1
        assert result[0].raw_text == long.raw_text

    def test_distinct_claims_both_kept(self) -> None:
        a = _claim(
            "We will reach net zero by 2040.",
            category=ClaimCategory.NET_ZERO_TARGET,
        )
        b = _claim(
            "100% of our electricity comes from renewable sources.",
            category=ClaimCategory.RENEWABLE_ENERGY,
        )
        result = _deduplicate_claims([a, b])
        assert len(result) == 2

    def test_scope1_scope3_are_distinct(self) -> None:
        scope1 = _claim(
            "We have reduced Scope 1 and 2 emissions by 42% since 2019.",
            category=ClaimCategory.EMISSIONS_REDUCTION,
        )
        scope3 = _claim(
            "We are targeting a 30% reduction in Scope 3 value-chain emissions by 2030.",
            category=ClaimCategory.EMISSIONS_REDUCTION,
        )
        result = _deduplicate_claims([scope1, scope3])
        assert len(result) == 2, "Scope 1+2 and Scope 3 claims must not be collapsed"

    def test_near_duplicate_above_threshold_deduplicated(self) -> None:
        base = _claim("Achieve net zero carbon emissions across operations by 2050.")
        near = _claim("Achieve net zero carbon emissions by 2050.")
        result = _deduplicate_claims([base, near])
        assert len(result) == 1

    def test_empty_text_claim_is_kept_not_collapsed(self) -> None:
        empty = _claim("")
        normal = _claim("We will reach net zero by 2040.")
        result = _deduplicate_claims([empty, normal])
        assert len(result) == 2

    def test_distinct_texts_not_collapsed_at_any_threshold(self) -> None:
        # Fully independent claims with no token overlap — never collapsed.
        a = _claim("Our renewable electricity procurement reached 100% globally.")
        b = _claim("Scope 3 supplier engagement programme covers 92% of spend.")
        result = _deduplicate_claims([a, b])
        assert len(result) == 2

    def test_order_independent(self) -> None:
        # Short claim whose tokens are all contained in the longer version.
        # Function sorts by length before processing, so result is identical
        # regardless of input order — and the longer version is always kept.
        long = _claim(
            "We commit to achieving net zero carbon emissions by the year 2050 commitment."
        )
        short = _claim("commit achieving net zero carbon emissions 2050")
        result_ab = _deduplicate_claims([long, short])
        result_ba = _deduplicate_claims([short, long])
        assert len(result_ab) == 1
        assert len(result_ba) == 1
        assert result_ab[0].raw_text == result_ba[0].raw_text == long.raw_text


# ---------------------------------------------------------------------------
# _diversify_claims
# ---------------------------------------------------------------------------


class TestDiversifyClaims:
    def test_empty_list_returns_empty(self) -> None:
        assert _diversify_claims([], max_claims=5) == []

    def test_fewer_than_max_returns_all(self) -> None:
        claims = [
            _claim("Net zero by 2040.", ClaimCategory.NET_ZERO_TARGET),
            _claim("100% renewable energy.", ClaimCategory.RENEWABLE_ENERGY),
        ]
        result = _diversify_claims(claims, max_claims=5)
        assert len(result) == 2

    def test_respects_max_claims(self) -> None:
        claims = [_claim(f"Claim {i}", ClaimCategory.NET_ZERO_TARGET) for i in range(10)]
        result = _diversify_claims(claims, max_claims=3)
        assert len(result) == 3

    def test_one_per_category_first_pass(self) -> None:
        claims = [
            _claim("Net zero A.", ClaimCategory.NET_ZERO_TARGET),
            _claim("Net zero B.", ClaimCategory.NET_ZERO_TARGET),
            _claim("Renewable A.", ClaimCategory.RENEWABLE_ENERGY),
            _claim("Renewable B.", ClaimCategory.RENEWABLE_ENERGY),
            _claim("SBTi validated.", ClaimCategory.SCIENCE_BASED_TARGETS),
        ]
        result = _diversify_claims(claims, max_claims=3)
        categories = [c.claim_category.value for c in result]
        assert len(set(categories)) == 3, "First 3 slots must be distinct categories"

    def test_fills_remaining_slots_after_diversity_pass(self) -> None:
        claims = [
            _claim("Net zero A.", ClaimCategory.NET_ZERO_TARGET),
            _claim("Renewable A.", ClaimCategory.RENEWABLE_ENERGY),
            _claim("Net zero B.", ClaimCategory.NET_ZERO_TARGET),
            _claim("Net zero C.", ClaimCategory.NET_ZERO_TARGET),
        ]
        result = _diversify_claims(claims, max_claims=4)
        assert len(result) == 4
        categories = [c.claim_category.value for c in result]
        assert categories.count(ClaimCategory.NET_ZERO_TARGET.value) == 3

    def test_max_claims_zero_returns_empty(self) -> None:
        claims = [_claim("Net zero by 2040.", ClaimCategory.NET_ZERO_TARGET)]
        result = _diversify_claims(claims, max_claims=0)
        assert result == []

    def test_preserves_input_order_within_category(self) -> None:
        claims = [
            _claim("First net zero claim.", ClaimCategory.NET_ZERO_TARGET),
            _claim("Renewable A.", ClaimCategory.RENEWABLE_ENERGY),
            _claim("Second net zero claim.", ClaimCategory.NET_ZERO_TARGET),
        ]
        result = _diversify_claims(claims, max_claims=3)
        nz_claims = [c for c in result if c.claim_category == ClaimCategory.NET_ZERO_TARGET]
        assert nz_claims[0].raw_text == "First net zero claim."


# ---------------------------------------------------------------------------
# _claim_priority_score
# ---------------------------------------------------------------------------


class TestClaimPriorityScore:
    def test_returns_positive_integer(self) -> None:
        c = _claim("We will reach net zero by 2040.")
        assert _claim_priority_score(c) > 0

    def test_specific_claim_beats_vague(self) -> None:
        vague = _claim("We are committed to sustainability.", ClaimCategory.NET_ZERO_TARGET)
        specific = _claim(
            "We will reduce Scope 1 emissions by 46% by 2030 from a 2019 baseline, "
            "capturing 200,000 tonnes of CO2 from 2029.",
            ClaimCategory.NET_ZERO_TARGET,
        )
        assert _claim_priority_score(specific) > _claim_priority_score(vague)

    def test_compound_bonus_for_quantity_plus_year(self) -> None:
        without_compound = _claim("We aim to reach net zero.")
        with_compound = _claim("We will capture 200,000 tonnes of CO2 from 2029.")
        assert _claim_priority_score(with_compound) > _claim_priority_score(without_compound)

    def test_net_zero_category_scores_higher_than_other(self) -> None:
        net_zero = _claim("Same text here.", ClaimCategory.NET_ZERO_TARGET)
        other = _claim("Same text here.", ClaimCategory.OTHER)
        assert _claim_priority_score(net_zero) > _claim_priority_score(other)

    def test_technology_bonus_applied(self) -> None:
        without_tech = _claim("We will reduce emissions by 2040.")
        with_tech = _claim("We will deploy CCS technology to reduce emissions by 2040.")
        assert _claim_priority_score(with_tech) > _claim_priority_score(without_tech)

    def test_empty_text_does_not_raise(self) -> None:
        c = _claim("")
        score = _claim_priority_score(c)
        assert isinstance(score, int)


# ---------------------------------------------------------------------------
# GreenwashingScore — empco_violation field
# ---------------------------------------------------------------------------


class TestGreenwashingScoreEmpcoViolation:
    def _base_score_kwargs(self) -> dict:
        return {
            "claim_id": uuid.uuid4(),
            "company_id": _COMPANY_ID,
            "trace_id": _TRACE_ID,
            "score": 72.0,
            "verdict": "LIKELY_GREENWASHING",
            "reasoning": "Test reasoning.",
            "confidence": 0.8,
            "judge_model_id": "claude-opus-4-8",
        }

    def test_empco_violation_defaults_to_none(self) -> None:
        from models.score import GreenwashingScore

        score = GreenwashingScore(**self._base_score_kwargs())
        assert score.empco_violation is None

    def test_empco_violation_true(self) -> None:
        from models.score import GreenwashingScore

        score = GreenwashingScore(**self._base_score_kwargs(), empco_violation=True)
        assert score.empco_violation is True

    def test_empco_violation_false(self) -> None:
        from models.score import GreenwashingScore

        score = GreenwashingScore(**self._base_score_kwargs(), empco_violation=False)
        assert score.empco_violation is False

    def test_score_is_frozen(self) -> None:
        from pydantic import ValidationError

        from models.score import GreenwashingScore

        score = GreenwashingScore(**self._base_score_kwargs(), empco_violation=True)
        with pytest.raises((ValidationError, TypeError)):
            score.empco_violation = False  # type: ignore[misc]

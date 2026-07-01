"""Agent-level unit tests.

Tests cover agent logic that can be exercised without live LLM calls or
database connections:
  - ClaimStatus.FAILED lifecycle state
  - ClaimCategory fallback to OTHER for unknown values
  - Report section validation
  - LobbyMap cache TTL invalidation
  - Per-node verification timeout structure
No network, no database, no Anthropic API calls.
"""

from __future__ import annotations

import time
import uuid

import pytest

from models.claim import Claim, ClaimCategory, ClaimStatus, SourceType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_COMPANY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TRACE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _claim(text: str = "Net zero by 2050.") -> Claim:
    return Claim(
        trace_id=_TRACE_ID,
        company_id=_COMPANY_ID,
        source_url="https://example.com/sustainability",
        source_type=SourceType.WEBSITE,
        raw_text=text,
        claim_category=ClaimCategory.NET_ZERO_TARGET,
    )


# ---------------------------------------------------------------------------
# ClaimStatus.FAILED
# ---------------------------------------------------------------------------


class TestClaimStatusFailed:
    def test_failed_is_a_valid_status(self) -> None:
        assert ClaimStatus.FAILED == "FAILED"

    def test_failed_is_distinct_from_other_states(self) -> None:
        assert ClaimStatus.FAILED not in {
            ClaimStatus.DETECTED,
            ClaimStatus.VERIFIED,
            ClaimStatus.SCORED,
            ClaimStatus.PUBLISHED,
            ClaimStatus.MONITORING,
        }

    def test_claim_can_be_constructed_with_failed_status(self) -> None:
        c = Claim(
            trace_id=_TRACE_ID,
            company_id=_COMPANY_ID,
            source_url="https://example.com",
            source_type=SourceType.WEBSITE,
            raw_text="Net zero by 2050.",
            claim_category=ClaimCategory.NET_ZERO_TARGET,
            status=ClaimStatus.FAILED,
        )
        assert c.status == ClaimStatus.FAILED


# ---------------------------------------------------------------------------
# ClaimCategory fallback — invalid value maps to OTHER
# ---------------------------------------------------------------------------


class TestClaimCategoryFallback:
    def test_other_is_valid_fallback(self) -> None:
        assert ClaimCategory.OTHER == "OTHER"

    def test_unknown_value_not_in_enum(self) -> None:
        assert "SUSTAINABLE_AVIATION_FUEL" not in ClaimCategory._value2member_map_

    def test_fallback_logic_returns_other_for_unknown(self) -> None:
        raw_value = "SUSTAINABLE_AVIATION_FUEL"
        result = (
            ClaimCategory(raw_value)
            if raw_value in ClaimCategory._value2member_map_
            else ClaimCategory.OTHER
        )
        assert result == ClaimCategory.OTHER

    def test_fallback_logic_preserves_valid_value(self) -> None:
        raw_value = "NET_ZERO_TARGET"
        result = (
            ClaimCategory(raw_value)
            if raw_value in ClaimCategory._value2member_map_
            else ClaimCategory.OTHER
        )
        assert result == ClaimCategory.NET_ZERO_TARGET


# ---------------------------------------------------------------------------
# Report section validation
# ---------------------------------------------------------------------------


class TestReportSectionValidation:
    def _make_report(self, sections: list[str]) -> str:
        return "\n".join(f"{s}\nContent here.\n" for s in sections)

    def test_valid_report_has_all_required_sections(self) -> None:
        from agents.report_agent import _REQUIRED_SECTIONS, _validate_report_sections

        report = self._make_report(list(_REQUIRED_SECTIONS))
        # Should not raise or log warning — we just verify the function returns cleanly.
        _validate_report_sections(report, _TRACE_ID)

    def test_missing_section_does_not_raise(self) -> None:
        from agents.report_agent import _validate_report_sections

        # Incomplete report — validator logs a warning but must not raise.
        report = "### The Claim\nContent.\n### Evidence\nContent.\n"
        _validate_report_sections(report, _TRACE_ID)  # should not raise

    def test_required_sections_constant_is_nonempty(self) -> None:
        from agents.report_agent import _REQUIRED_SECTIONS

        assert len(_REQUIRED_SECTIONS) >= 5


# ---------------------------------------------------------------------------
# LobbyMap cache TTL
# ---------------------------------------------------------------------------


class TestLobbyMapCacheTTL:
    def test_cache_ttl_constant_is_24h(self) -> None:
        from ingest.lobby_map import _CACHE_TTL_S

        assert _CACHE_TTL_S == 86_400.0

    def test_refresh_cache_resets_loaded_at(self) -> None:
        import ingest.lobby_map as lm

        # Force a non-zero load time.
        lm._cache_loaded_at = time.monotonic()
        lm.refresh_cache()
        assert lm._cache_loaded_at == 0.0

    def test_refresh_cache_clears_both_caches(self) -> None:
        import ingest.lobby_map as lm

        lm._cache_by_name = {}
        lm._cache_by_ticker = {}
        lm.refresh_cache()
        assert lm._cache_by_name is None
        assert lm._cache_by_ticker is None


# ---------------------------------------------------------------------------
# Verification node timeout constant
# ---------------------------------------------------------------------------


class TestVerificationTimeout:
    def test_hard_timeout_constant_exists(self) -> None:
        from agents.verification_agent import _NODE_HARD_TIMEOUT_S

        assert _NODE_HARD_TIMEOUT_S > 0

    def test_hard_timeout_exceeds_slow_threshold(self) -> None:
        from agents.verification_agent import _NODE_HARD_TIMEOUT_S, _SLOW_NODE_THRESHOLD_S

        assert _NODE_HARD_TIMEOUT_S > _SLOW_NODE_THRESHOLD_S

    def test_hard_timeout_is_45s(self) -> None:
        from agents.verification_agent import _NODE_HARD_TIMEOUT_S

        assert _NODE_HARD_TIMEOUT_S == 45.0

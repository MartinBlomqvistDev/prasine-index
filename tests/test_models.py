# Unit tests for the Prasine Index Pydantic v2 domain model layer. Covers field
# validation, model validators, enum correctness, and the invariants that agent
# code relies on (e.g. repeat claims must carry a previous_claim_id, FAILURE
# traces must carry error context). Tests are intentionally fast and have zero
# external dependencies: no database, no LLM, no HTTP.

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from models.claim import Claim, ClaimCategory, ClaimLifecycle, ClaimStatus, SourceType
from models.company import Company
from models.evidence import Evidence, EvidenceSource, EvidenceType
from models.score import GreenwashingScore, ScoreCategory, ScoreVerdict
from models.trace import AgentName, AgentOutcome, AgentTrace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def company_id() -> uuid.UUID:
    """Return a fixed company UUID for use across tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def trace_id() -> uuid.UUID:
    """Return a fixed trace UUID for use across tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
def claim_id() -> uuid.UUID:
    """Return a fixed claim UUID for use across tests."""
    return uuid.UUID("00000000-0000-0000-0000-000000000003")


@pytest.fixture
def minimal_claim(company_id: uuid.UUID, trace_id: uuid.UUID) -> Claim:
    """Return a valid minimal Claim for use as a building block in tests."""
    return Claim(
        trace_id=trace_id,
        company_id=company_id,
        source_url="https://example.com/report.pdf",
        source_type=SourceType.CSRD_REPORT,
        raw_text="We will achieve net zero by 2040.",
    )


@pytest.fixture
def minimal_company(company_id: uuid.UUID) -> Company:
    """Return a valid minimal Company for use in tests."""
    return Company(
        id=company_id,
        name="Acme Energy AG",
        country="DE",
        sector="Energy",
    )


# ---------------------------------------------------------------------------
# Claim tests
# ---------------------------------------------------------------------------

class TestClaim:
    """Tests for the Claim model."""

    def test_default_status_is_detected(self, minimal_claim: Claim) -> None:
        """Claim status defaults to DETECTED on construction."""
        assert minimal_claim.status == ClaimStatus.DETECTED

    def test_ids_are_generated_automatically(self, minimal_claim: Claim) -> None:
        """Claim.id and trace_id are non-null UUIDs."""
        assert isinstance(minimal_claim.id, uuid.UUID)
        assert isinstance(minimal_claim.trace_id, uuid.UUID)

    def test_repeat_claim_requires_previous_id(self, company_id: uuid.UUID) -> None:
        """Repeat claims must supply previous_claim_id; omitting it raises ValidationError."""
        with pytest.raises(ValidationError, match="previous_claim_id"):
            Claim(
                company_id=company_id,
                source_url="https://example.com",
                source_type=SourceType.PRESS_RELEASE,
                raw_text="We are carbon neutral.",
                is_repeat=True,
                previous_claim_id=None,  # invalid: is_repeat=True but no previous_claim_id
            )

    def test_repeat_claim_with_previous_id_is_valid(self, company_id: uuid.UUID) -> None:
        """Repeat claims with a previous_claim_id pass validation."""
        prior_id = uuid.uuid4()
        claim = Claim(
            company_id=company_id,
            source_url="https://example.com",
            source_type=SourceType.PRESS_RELEASE,
            raw_text="We are carbon neutral.",
            is_repeat=True,
            previous_claim_id=prior_id,
        )
        assert claim.is_repeat is True
        assert claim.previous_claim_id == prior_id

    def test_modified_claim_requires_original_scored_text(self, company_id: uuid.UUID) -> None:
        """modified_after_scoring=True without original_scored_text raises ValidationError."""
        with pytest.raises(ValidationError, match="original_scored_text"):
            Claim(
                company_id=company_id,
                source_url="https://example.com",
                source_type=SourceType.PRESS_RELEASE,
                raw_text="We are carbon neutral.",
                modified_after_scoring=True,
                original_scored_text=None,
            )

    def test_modified_claim_with_original_text_is_valid(self, company_id: uuid.UUID) -> None:
        """modified_after_scoring with original_scored_text passes validation."""
        claim = Claim(
            company_id=company_id,
            source_url="https://example.com",
            source_type=SourceType.PRESS_RELEASE,
            raw_text="We are climate positive.",
            modified_after_scoring=True,
            original_scored_text="We are carbon neutral.",
        )
        assert claim.modified_after_scoring is True
        assert claim.original_scored_text == "We are carbon neutral."

    def test_claim_category_defaults_to_other(self, minimal_claim: Claim) -> None:
        """Claim with no explicit category defaults to OTHER."""
        claim = Claim(
            company_id=minimal_claim.company_id,
            source_url="https://example.com",
            source_type=SourceType.WEBSITE,
            raw_text="We are sustainable.",
        )
        assert claim.claim_category == ClaimCategory.OTHER

    def test_all_claim_categories_are_valid(self) -> None:
        """All ClaimCategory values are accessible as strings."""
        for cat in ClaimCategory:
            assert cat.value == cat


class TestClaimLifecycle:
    """Tests for the ClaimLifecycle model."""

    def test_lifecycle_is_frozen(self, claim_id: uuid.UUID) -> None:
        """ClaimLifecycle instances are immutable."""
        lifecycle = ClaimLifecycle(
            claim_id=claim_id,
            to_status=ClaimStatus.VERIFIED,
            transitioned_by="verification_agent",
        )
        with pytest.raises(ValidationError):
            lifecycle.to_status = ClaimStatus.SCORED  # type: ignore[misc]

    def test_initial_transition_has_no_from_status(self, claim_id: uuid.UUID) -> None:
        """First lifecycle entry (DETECTED) has from_status=None."""
        lifecycle = ClaimLifecycle(
            claim_id=claim_id,
            from_status=None,
            to_status=ClaimStatus.DETECTED,
            transitioned_by="system",
        )
        assert lifecycle.from_status is None
        assert lifecycle.to_status == ClaimStatus.DETECTED


# ---------------------------------------------------------------------------
# Company tests
# ---------------------------------------------------------------------------

class TestCompany:
    """Tests for the Company model."""

    def test_lei_must_be_20_alphanumeric_chars(self, company_id: uuid.UUID) -> None:
        """Invalid LEI format raises ValidationError."""
        with pytest.raises(ValidationError, match="LEI"):
            Company(
                id=company_id,
                name="Test Corp",
                country="DE",
                sector="Energy",
                lei="SHORT",  # invalid
            )

    def test_valid_lei_is_normalised_to_uppercase(self, company_id: uuid.UUID) -> None:
        """Valid LEI is normalised to uppercase."""
        company = Company(
            id=company_id,
            name="Test Corp",
            country="DE",
            sector="Energy",
            lei="529900T8BM49AURSDO55",  # valid 20-char LEI
        )
        assert company.lei == "529900T8BM49AURSDO55"

    def test_isin_must_be_12_alphanumeric_chars(self, company_id: uuid.UUID) -> None:
        """Invalid ISIN format raises ValidationError."""
        with pytest.raises(ValidationError, match="ISIN"):
            Company(
                id=company_id,
                name="Test Corp",
                country="DE",
                sector="Energy",
                isin="TOOLONG1234567",
            )

    def test_country_code_normalised_to_uppercase(self, company_id: uuid.UUID) -> None:
        """Country code is normalised to uppercase regardless of input case."""
        company = Company(
            id=company_id,
            name="Test Corp",
            country="de",
            sector="Energy",
        )
        assert company.country == "DE"

    def test_eu_ets_installation_ids_defaults_to_empty(self, minimal_company: Company) -> None:
        """eu_ets_installation_ids defaults to an empty list."""
        assert minimal_company.eu_ets_installation_ids == []


# ---------------------------------------------------------------------------
# Evidence tests
# ---------------------------------------------------------------------------

class TestEvidence:
    """Tests for the Evidence model."""

    def test_evidence_is_frozen(self, claim_id: uuid.UUID, trace_id: uuid.UUID) -> None:
        """Evidence instances are immutable."""
        ev = Evidence(
            claim_id=claim_id,
            trace_id=trace_id,
            source=EvidenceSource.EU_ETS,
            evidence_type=EvidenceType.VERIFIED_EMISSIONS,
            summary="Test summary.",
        )
        with pytest.raises(ValidationError):
            ev.summary = "modified"  # type: ignore[misc]

    def test_confidence_must_be_in_unit_range(self, claim_id: uuid.UUID, trace_id: uuid.UUID) -> None:
        """Confidence outside [0.0, 1.0] raises ValidationError."""
        with pytest.raises(ValidationError):
            Evidence(
                claim_id=claim_id,
                trace_id=trace_id,
                source=EvidenceSource.EU_ETS,
                evidence_type=EvidenceType.VERIFIED_EMISSIONS,
                summary="Test.",
                confidence=1.5,  # invalid
            )

    def test_data_year_must_be_plausible(self, claim_id: uuid.UUID, trace_id: uuid.UUID) -> None:
        """data_year outside [1990, 2100] raises ValidationError."""
        with pytest.raises(ValidationError, match="plausible"):
            Evidence(
                claim_id=claim_id,
                trace_id=trace_id,
                source=EvidenceSource.CDP,
                evidence_type=EvidenceType.SELF_REPORTED_EMISSIONS,
                summary="Test.",
                data_year=1850,  # invalid
            )

    def test_supports_claim_can_be_none(self, claim_id: uuid.UUID, trace_id: uuid.UUID) -> None:
        """supports_claim=None (inconclusive) is a valid value."""
        ev = Evidence(
            claim_id=claim_id,
            trace_id=trace_id,
            source=EvidenceSource.EUR_LEX,
            evidence_type=EvidenceType.LEGISLATIVE_RECORD,
            summary="Legislative context only.",
            supports_claim=None,
        )
        assert ev.supports_claim is None


# ---------------------------------------------------------------------------
# GreenwashingScore tests
# ---------------------------------------------------------------------------

class TestGreenwashingScore:
    """Tests for the GreenwashingScore model."""

    def test_score_is_frozen(
        self,
        claim_id: uuid.UUID,
        company_id: uuid.UUID,
        trace_id: uuid.UUID,
    ) -> None:
        """GreenwashingScore instances are immutable."""
        score = GreenwashingScore(
            claim_id=claim_id,
            company_id=company_id,
            trace_id=trace_id,
            score=75.0,
            verdict=ScoreVerdict.GREENWASHING,
            reasoning="Test reasoning.",
            confidence=0.85,
            judge_model_id="claude-opus-4-6",
        )
        with pytest.raises(ValidationError):
            score.score = 50.0  # type: ignore[misc]

    def test_score_must_be_in_range(
        self,
        claim_id: uuid.UUID,
        company_id: uuid.UUID,
        trace_id: uuid.UUID,
    ) -> None:
        """Score outside [0.0, 100.0] raises ValidationError."""
        with pytest.raises(ValidationError):
            GreenwashingScore(
                claim_id=claim_id,
                company_id=company_id,
                trace_id=trace_id,
                score=101.0,  # invalid
                verdict=ScoreVerdict.GREENWASHING,
                reasoning="Test.",
                confidence=0.9,
                judge_model_id="claude-opus-4-6",
            )

    def test_score_breakdown_invalid_key_raises(
        self,
        claim_id: uuid.UUID,
        company_id: uuid.UUID,
        trace_id: uuid.UUID,
    ) -> None:
        """Invalid ScoreCategory key in score_breakdown raises ValidationError."""
        with pytest.raises(ValidationError, match="ScoreCategory"):
            GreenwashingScore(
                claim_id=claim_id,
                company_id=company_id,
                trace_id=trace_id,
                score=50.0,
                score_breakdown={"INVALID_DIMENSION": 60.0},  # invalid key
                verdict=ScoreVerdict.MISLEADING,
                reasoning="Test.",
                confidence=0.7,
                judge_model_id="claude-opus-4-6",
            )

    def test_score_breakdown_valid_key_passes(
        self,
        claim_id: uuid.UUID,
        company_id: uuid.UUID,
        trace_id: uuid.UUID,
    ) -> None:
        """Valid ScoreCategory keys in score_breakdown pass validation."""
        score = GreenwashingScore(
            claim_id=claim_id,
            company_id=company_id,
            trace_id=trace_id,
            score=60.0,
            score_breakdown={
                ScoreCategory.EMISSIONS_ACCURACY.value: 70.0,
                ScoreCategory.HISTORICAL_CONSISTENCY.value: 55.0,
            },
            verdict=ScoreVerdict.GREENWASHING,
            reasoning="Test.",
            confidence=0.8,
            judge_model_id="claude-opus-4-6",
        )
        assert score.score_breakdown[ScoreCategory.EMISSIONS_ACCURACY.value] == 70.0


# ---------------------------------------------------------------------------
# AgentTrace tests
# ---------------------------------------------------------------------------

class TestAgentTrace:
    """Tests for the AgentTrace model."""

    def test_failure_trace_requires_error_context(self, trace_id: uuid.UUID) -> None:
        """FAILURE outcome without error_type or error_message raises ValidationError."""
        with pytest.raises(ValidationError, match="FAILURE"):
            AgentTrace(
                trace_id=trace_id,
                agent=AgentName.EXTRACTION,
                outcome=AgentOutcome.FAILURE,
                input_schema="agents.extraction_agent.ExtractionInput",
                started_at=datetime.now(UTC),
                # neither error_type nor error_message provided — invalid
            )

    def test_failure_trace_with_error_type_is_valid(self, trace_id: uuid.UUID) -> None:
        """FAILURE outcome with error_type passes validation."""
        trace = AgentTrace(
            trace_id=trace_id,
            agent=AgentName.EXTRACTION,
            outcome=AgentOutcome.FAILURE,
            input_schema="agents.extraction_agent.ExtractionInput",
            started_at=datetime.now(UTC),
            error_type="httpx.TimeoutException",
        )
        assert trace.outcome == AgentOutcome.FAILURE

    def test_completed_at_cannot_precede_started_at(self, trace_id: uuid.UUID) -> None:
        """completed_at before started_at raises ValidationError."""
        now = datetime.now(UTC)
        earlier = datetime(2020, 1, 1, tzinfo=UTC)
        with pytest.raises(ValidationError, match="cannot precede"):
            AgentTrace(
                trace_id=trace_id,
                agent=AgentName.JUDGE,
                outcome=AgentOutcome.SUCCESS,
                input_schema="agents.judge_agent.JudgeInput",
                started_at=now,
                completed_at=earlier,  # invalid: before started_at
            )

    def test_duration_ms_requires_completed_at(self, trace_id: uuid.UUID) -> None:
        """duration_ms without completed_at raises ValidationError."""
        with pytest.raises(ValidationError, match="duration_ms requires"):
            AgentTrace(
                trace_id=trace_id,
                agent=AgentName.JUDGE,
                outcome=AgentOutcome.SUCCESS,
                input_schema="agents.judge_agent.JudgeInput",
                started_at=datetime.now(UTC),
                duration_ms=1500,
                completed_at=None,  # invalid: duration set but no completed_at
            )

    def test_success_trace_requires_no_error_fields(self, trace_id: uuid.UUID) -> None:
        """SUCCESS trace with no error fields is valid."""
        now = datetime.now(UTC)
        trace = AgentTrace(
            trace_id=trace_id,
            agent=AgentName.REPORT,
            outcome=AgentOutcome.SUCCESS,
            input_schema="agents.report_agent.ReportInput",
            output_schema="agents.report_agent.ReportResult",
            started_at=now,
            completed_at=now,
            duration_ms=0,
        )
        assert trace.error_type is None
        assert trace.error_message is None

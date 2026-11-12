"""Regression cases for the Prasine Index pipeline.

The 20 cases are climate claims of named companies, each with the label and
score range the pipeline was expected to give under version 1 of the method.
The labels are the internal names of the score bands in models/score.py and
describe score ranges only. Several expected labels were set to match the
pipeline's own output at the time, and some claim texts are not the companies'
exact words. A case is therefore not a judgement of the company or its claim.
The expected labels and ranges have not been re-set for version 2.

The runner executes the full pipeline on each case and reports how many cases
match their expected label and score range, the time per case and the tokens
used. It is a regression check and does not measure accuracy. It runs by hand
or from the manual Eval workflow (.github/workflows/eval.yml); it does not run
on every push.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agents.extraction_agent import ExtractionInput
from core.logger import get_logger, setup_logging
from core.pipeline import Pipeline, PipelineConfig
from models.claim import ClaimCategory, SourceType
from models.score import ScoreVerdict

__all__ = [
    "GOLDEN_DATASET",
    "QUICK_CASES",
    "EvalCase",
    "EvalResult",
    "EvalSummary",
    "run_eval",
]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class EvalCase(BaseModel):
    """A regression case with the label and score range expected under version 1.

    Attributes:
        case_id: Unique identifier for this eval case.
        company_id: UUID of the seeded company in the database.
        company_name: Company the claim is attributed to.
        company_country: ISO 3166-1 alpha-2 country of the company.
        claim_text: The claim text as tested; not the company's exact words in
            some cases.
        claim_category: Expected claim category.
        source_type: Document type recorded for the claim.
        source_url: Source URL (may be a placeholder for historical cases).
        expected_verdict: The label expected under version 1 of the method.
        expected_score_min: Lowest score in the expected range.
        expected_score_max: Highest score in the expected range.
        primary_evidence_source: The source the case was expected to turn on.
        notes: Provenance of the case and of any decision it cites.
        tier: must_pass, or known_limitation for a case left out of the
            must_pass rate; both count towards the overall rate.
    """

    model_config = ConfigDict(from_attributes=True)

    case_id: str
    company_id: uuid.UUID
    company_name: str
    company_country: str
    claim_text: str
    claim_category: ClaimCategory
    source_type: SourceType
    source_url: str
    expected_verdict: ScoreVerdict
    expected_score_min: float
    expected_score_max: float
    primary_evidence_source: str
    notes: str
    tier: Literal["must_pass", "known_limitation"] = "must_pass"


class EvalResult(BaseModel):
    """Result of running a single eval case through the pipeline.

    Attributes:
        case_id: The eval case that was run.
        verdict_correct: Whether the pipeline's label matched the expected label.
        score_in_range: Whether the pipeline score was within the expected range.
        actual_verdict: The label the pipeline produced.
        actual_score: The score the pipeline produced.
        duration_ms: Total wall-clock time for the full pipeline run.
        tokens_used: Total tokens consumed across all LLM agent steps.
        error: Error message if the pipeline failed, None on success.
    """

    model_config = ConfigDict(from_attributes=True)

    case_id: str
    verdict_correct: bool
    score_in_range: bool
    actual_verdict: ScoreVerdict | None
    actual_score: float | None
    duration_ms: int
    tokens_used: int
    error: str | None = None

    @property
    def passed(self) -> bool:
        """True if the label and the score both match the expectation.

        Returns:
            True if both match and the run raised no error.
        """
        return self.verdict_correct and self.score_in_range and self.error is None


class EvalSummary(BaseModel):
    """Aggregate results of a run of the regression cases.

    Attributes:
        total_cases: Total number of cases run.
        passed: Number of cases whose label and score both match the expectation.
        failed: Number of cases that do not match, leaving out errors.
        errors: Number of cases where the pipeline raised an exception.
        verdict_accuracy: Fraction of cases whose label matches the expected
            label; printed as Band match.
        score_accuracy: Fraction of cases whose score is in the expected range;
            printed as Score in range.
        overall_pass_rate: Fraction of cases that match both their expected
            label and their expected score range.
        tier1_pass_rate: Pass rate for must_pass cases only, reported beside the
            overall rate; the exit code uses the overall rate.
        avg_duration_ms: Mean wall-clock time per case.
        total_tokens_used: Total tokens consumed across all cases.
        cases: The EvalCase definitions, parallel to results, for tier lookups.
        results: Individual results for each case.
    """

    model_config = ConfigDict(from_attributes=True)

    total_cases: int
    passed: int
    failed: int
    errors: int
    verdict_accuracy: float
    score_accuracy: float
    overall_pass_rate: float
    tier1_pass_rate: float
    avg_duration_ms: float
    total_tokens_used: int
    cases: list[EvalCase]
    results: list[EvalResult]

    def report(self) -> str:
        """Generate a plain-text eval summary report.

        Returns:
            A formatted multi-line report string.
        """
        tier1_results = [
            r for r, c in zip(self.results, self.cases, strict=True) if c.tier == "must_pass"
        ]
        tier2_results = [
            r for r, c in zip(self.results, self.cases, strict=True) if c.tier == "known_limitation"
        ]
        tier1_passed = sum(1 for r in tier1_results if r.passed)
        tier2_passed = sum(1 for r in tier2_results if r.passed)

        lines = [
            "=" * 60,
            "PRASINE INDEX: GOLDEN DATASET EVAL RESULTS",
            "=" * 60,
            f"Total cases:       {self.total_cases}",
            f"Tier-1 (must_pass):{tier1_passed}/{len(tier1_results)} ({self.tier1_pass_rate:.1%})",
            f"Tier-2:            {tier2_passed}/{len(tier2_results)} (known_limitation, counted in Overall)",
            f"Overall:           {self.passed}/{self.total_cases} ({self.overall_pass_rate:.1%})",
            f"Failed:            {self.failed}",
            f"Errors:            {self.errors}",
            f"Band match:        {self.verdict_accuracy:.1%}",
            f"Score in range:    {self.score_accuracy:.1%}",
            f"Avg duration:      {self.avg_duration_ms:.0f}ms",
            f"Total tokens:      {self.total_tokens_used:,}",
            "=" * 60,
            "CASE RESULTS:",
        ]
        for r, c in zip(self.results, self.cases, strict=True):
            status = "PASS" if r.passed else ("ERROR" if r.error else "FAIL")
            tier_tag = "T1" if c.tier == "must_pass" else "T2"
            score_str = f"{r.actual_score:.1f}" if r.actual_score is not None else "N/A"
            verdict_str = r.actual_verdict.value if r.actual_verdict else "N/A"
            lines.append(
                f"  [{status}][{tier_tag}] {r.case_id:28s} | "
                f"band={verdict_str:25s} | score={score_str:6s} | "
                f"{r.duration_ms}ms"
            )
            if r.error:
                lines.append(f"           ERROR: {r.error}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Golden dataset: 20 regression cases, expected labels from version 1 of the method
# ---------------------------------------------------------------------------

GOLDEN_DATASET: list[EvalCase] = [
    EvalCase(
        case_id="GW-001",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        company_name="Ryanair Holdings plc",
        company_country="IE",
        claim_text="Ryanair is Europe's greenest airline.",
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.WEBSITE,
        source_url="https://www.ryanair.com/gb/en/plan-trip/environment",
        expected_verdict=ScoreVerdict.CONFIRMED_GREENWASHING,
        expected_score_min=75.0,
        expected_score_max=95.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The UK ASA ruled on 5 February "
            "2020 (G19-1035778) that Ryanair's September 2019 ads calling it Europe's "
            "'Lowest Emissions Airline' were misleading. LobbyMap rates Ryanair D "
            "(5 November 2026), within the range it defines as obstructive. The enforcement "
            "module surfaces the ASA ruling as a decision on a related claim."
        ),
    ),
    EvalCase(
        case_id="GW-002",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        company_name="Volkswagen AG",
        company_country="DE",
        claim_text=(
            "Volkswagen is committed to becoming a net carbon-neutral company by 2050, "
            "with CO2-neutral production at all our sites by 2025."
        ),
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.ANNUAL_REPORT,
        source_url="https://annualreport2021.volkswagenag.com",
        expected_verdict=ScoreVerdict.MISLEADING_CLAIM,
        expected_score_min=45.0,
        expected_score_max=75.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The enforcement records hold one "
            "Volkswagen decision: the CPC network's declaration of 28 September 2021 on the "
            "marketing of diesel cars fitted with defeat devices, which concerns a different "
            "claim."
        ),
    ),
    EvalCase(
        case_id="GW-003",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000003"),
        company_name="Shell plc",
        company_country="GB",
        claim_text=(
            "Shell aims to be a net-zero emissions energy business by 2050, in step with society."
        ),
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://reports.shell.com/sustainability-report/2023",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=65.0,
        expected_score_max=92.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. In 2021 the Hague District Court "
            "ordered Shell to cut its CO2 emissions by 45% by 2030 against 2019; the Hague "
            "Court of Appeal overturned that order on 12 November 2024."
        ),
    ),
    EvalCase(
        case_id="GW-004",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000004"),
        company_name="Eni SpA",
        company_country="IT",
        claim_text="Eni's products are certified carbon neutral.",
        claim_category=ClaimCategory.CARBON_NEUTRAL,
        source_type=SourceType.PRESS_RELEASE,
        source_url="https://www.eni.com/en-IT/media/press-release/2021",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=65.0,
        expected_score_max=95.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. Italy's AGCM fined Eni EUR 5 million "
            "on 20 December 2019, finding its Eni Diesel+ advertising misleading; the "
            "Consiglio di Stato annulled that decision on 23 April 2024 (judgment "
            "n. 03701/2024), so neither the finding nor the fine stands. The claim text is "
            "not tied to a specific Eni document; the source URL is a general press-release "
            "page."
        ),
    ),
    EvalCase(
        case_id="GW-005",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000005"),
        company_name="Nestlé S.A.",
        company_country="CH",
        claim_text="Nestlé is committed to achieving net zero greenhouse gas emissions by 2050.",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.ANNUAL_REPORT,
        source_url="https://www.nestle.com/sustainability/climate-change/net-zero",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=46.0,
        expected_score_max=75.0,
        primary_evidence_source="CDP",
        notes=(
            "Expected label from version 1 of the method. Nestlé's Net Zero Roadmap covers "
            "Scopes 1, 2 and 3, leaving out some Scope 3 categories, and its targets are "
            "validated by the SBTi."
        ),
    ),
    EvalCase(
        case_id="GW-006",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000006"),
        company_name="Deutsche Lufthansa AG",
        company_country="DE",
        claim_text=(
            "Sustainable Aviation Fuel will allow us to achieve CO2-neutral flying in the future."
        ),
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.IR_PAGE,
        source_url="https://investor-relations.lufthansagroup.com/en/responsibility/environment",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=61.0,
        expected_score_max=82.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The enforcement records hold two "
            "ASA rulings on Lufthansa ads (A22-1169419 of 1 March 2023 and A23-1206007 of "
            "6 December 2023) and the commitments Lufthansa made after a dialogue with the "
            "European Commission and the CPC network (IP/25/2608, 6 November 2025)."
        ),
    ),
    EvalCase(
        case_id="GW-007",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000007"),
        company_name="HeidelbergCement AG",
        company_country="DE",
        claim_text=(
            "We will reduce our specific net CO2 emissions per tonne of cementitious "
            "material by 30% by 2025 versus 1990."
        ),
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://www.heidelbergmaterials.com/en/sustainability",
        expected_verdict=ScoreVerdict.SUBSTANTIATED_CLAIM,
        expected_score_min=5.0,
        expected_score_max=35.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. HeidelbergCement AG is now "
            "Heidelberg Materials AG, listed as Heidelberg Materials in the SBTi and "
            "LobbyMap data."
        ),
        tier="known_limitation",
    ),
    EvalCase(
        case_id="GW-008",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000008"),
        company_name="TotalEnergies SE",
        company_country="FR",
        claim_text="TotalEnergies is transforming itself into a multi-energy company targeting net zero by 2050.",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.ANNUAL_REPORT,
        source_url="https://www.totalenergies.com/energy-expertise/climate-ambition",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=60.0,
        expected_score_max=90.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. At TotalEnergies' AGM on 26 May "
            "2023, a shareholder resolution asking it to align its 2030 Scope 3 target with "
            "the Paris Agreement received 30.44% of the votes and did not pass."
        ),
    ),
    EvalCase(
        case_id="GW-009",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000009"),
        company_name="HSBC Holdings plc",
        company_country="GB",
        claim_text=(
            "HSBC will align its portfolio of financed emissions to net zero by 2050 or sooner."
        ),
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.PRESS_RELEASE,
        source_url="https://www.hsbc.com/news-and-views/news/hsbc-news/2020/hsbc-sets-out-ambition-to-be-net-zero",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=61.0,
        expected_score_max=82.0,
        primary_evidence_source="CDP",
        notes=(
            "Expected label from version 1 of the method. The ASA ruled on 19 October 2022 "
            "(G21-1127656) that two HSBC bus-stop posters from October 2021 were misleading. "
            "Under version 2 the ASA ruling concerns a different claim and is context, and "
            "LobbyMap's C- band (5 November 2026) is outside the range it defines as "
            "obstructive."
        ),
    ),
    EvalCase(
        case_id="GW-010",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000010"),
        company_name="Ørsted A/S",
        company_country="DK",
        claim_text="Ørsted has reduced its carbon emissions by 87% since 2006.",
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://orsted.com/en/sustainability/our-approach/climate",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=56.0,
        expected_score_max=68.0,
        primary_evidence_source="EU_ETS",
        notes="Expected label from version 1 of the method.",
        tier="known_limitation",
    ),
    EvalCase(
        case_id="GW-011",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000011"),
        company_name="BP plc",
        company_country="GB",
        claim_text="BP has a net zero ambition — for our operations and our production, and for the carbon in the products we sell.",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.ANNUAL_REPORT,
        source_url="https://www.bp.com/en/global/corporate/sustainability/getting-to-net-zero.html",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=65.0,
        expected_score_max=92.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The only BP decision in the "
            "enforcement records is ASA G16-1014902 (2 October 2019), which did not uphold "
            "the complaints."
        ),
    ),
    EvalCase(
        case_id="GW-012",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000012"),
        company_name="ArcelorMittal S.A.",
        company_country="LU",
        claim_text=(
            "ArcelorMittal targets a 25% reduction in carbon emissions intensity by 2030 "
            "and net zero steel by 2050."
        ),
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://corporate.arcelormittal.com/sustainability/climate",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=61.0,
        expected_score_max=80.0,
        primary_evidence_source="EU_ETS",
        notes="Expected label from version 1 of the method.",
    ),
    EvalCase(
        case_id="GW-013",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000013"),
        company_name="Maersk A/S",
        company_country="DK",
        claim_text=(
            "Maersk targets net zero greenhouse gas emissions across our entire business "
            "by 2040, ten years ahead of the Paris Agreement timeline."
        ),
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://www.maersk.com/sustainability",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=56.0,
        expected_score_max=72.0,
        primary_evidence_source="CDP",
        notes="Expected label from version 1 of the method.",
        tier="known_limitation",
    ),
    EvalCase(
        case_id="GW-014",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000014"),
        company_name="Glencore plc",
        company_country="GB",
        claim_text="Glencore is committed to achieving net zero total emissions by 2050.",
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.ANNUAL_REPORT,
        source_url="https://www.glencore.com/sustainability/climate-change",
        expected_verdict=ScoreVerdict.CONFIRMED_GREENWASHING,
        expected_score_min=65.0,
        expected_score_max=95.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The enforcement records hold no "
            "decision on Glencore."
        ),
    ),
    EvalCase(
        case_id="GW-015",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000015"),
        company_name="Airbus SE",
        company_country="NL",
        claim_text=(
            "Airbus is committed to bringing hydrogen-powered zero-emission commercial "
            "aircraft to market by 2035."
        ),
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.PRESS_RELEASE,
        source_url="https://www.airbus.com/en/innovation/zero-emission/hydrogen",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=46.0,
        expected_score_max=72.0,
        primary_evidence_source="EUR_LEX",
        notes="Expected label from version 1 of the method.",
        tier="known_limitation",
    ),
    EvalCase(
        case_id="GW-016",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000016"),
        company_name="Unilever PLC",
        company_country="GB",
        claim_text=(
            "Unilever has committed to achieving net zero emissions from all our products "
            "across the full value chain by 2039."
        ),
        claim_category=ClaimCategory.NET_ZERO_TARGET,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://www.unilever.com/planet-and-society/climate-action/",
        expected_verdict=ScoreVerdict.MISLEADING_CLAIM,
        expected_score_min=38.0,
        expected_score_max=65.0,
        primary_evidence_source="CDP",
        notes="Expected label from version 1 of the method.",
    ),
    EvalCase(
        case_id="GW-017",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        company_name="Volkswagen AG",
        company_country="DE",
        claim_text=(
            "By 2030, we aim for 70 per cent of our sales in Europe to be fully electric vehicles."
        ),
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.ANNUAL_REPORT,
        source_url="https://annualreport2022.volkswagenag.com",
        expected_verdict=ScoreVerdict.UNVERIFIABLE_CLAIM,
        expected_score_min=20.0,
        expected_score_max=50.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The claim states a target share "
            "of electric vehicles in sales and gives no emissions figure. The enforcement "
            "record is the same as for GW-002."
        ),
    ),
    EvalCase(
        case_id="GW-018",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000017"),
        company_name="Easyjet plc",
        company_country="GB",
        claim_text="easyJet offsets the carbon emissions from the fuel used for all its flights.",
        claim_category=ClaimCategory.CARBON_NEUTRAL,
        source_type=SourceType.WEBSITE,
        source_url="https://www.easyjet.com/en/sustainability",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=61.0,
        expected_score_max=82.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. easyJet is one of 21 airlines that "
            "committed to change practices on environmental claims after a dialogue with the "
            "European Commission and the CPC network (IP/25/2608, 6 November 2025)."
        ),
    ),
    EvalCase(
        case_id="GW-019",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000018"),
        company_name="Vestas Wind Systems A/S",
        company_country="DK",
        claim_text=(
            "Vestas has been carbon neutral since 2013 and targets zero waste to landfill "
            "from production by 2025."
        ),
        claim_category=ClaimCategory.CARBON_NEUTRAL,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://www.vestas.com/en/sustainability",
        expected_verdict=ScoreVerdict.MISLEADING_CLAIM,
        expected_score_min=40.0,
        expected_score_max=55.0,
        primary_evidence_source="EU_ETS",
        notes=(
            "Expected label from version 1 of the method. The claim text is not Vestas's own "
            "wording: on 6 January 2020 Vestas committed to become carbon neutral by 2030 "
            "without using carbon offsets."
        ),
        tier="known_limitation",
    ),
    EvalCase(
        case_id="GW-020",
        company_id=uuid.UUID("00000000-0000-0000-0000-000000000019"),
        company_name="LafargeHolcim (Holcim) Ltd",
        company_country="CH",
        claim_text=(
            "Holcim targets net zero concrete by 2050, reducing CO2 per tonne of cement "
            "by 20% by 2030 versus 2018 baseline."
        ),
        claim_category=ClaimCategory.EMISSIONS_REDUCTION,
        source_type=SourceType.CSRD_REPORT,
        source_url="https://www.holcim.com/sustainability/climate",
        expected_verdict=ScoreVerdict.LIKELY_GREENWASHING,
        expected_score_min=61.0,
        expected_score_max=80.0,
        primary_evidence_source="EU_ETS",
        notes="Expected label from version 1 of the method.",
    ),
]


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------


async def run_eval(
    pipeline: Pipeline | None = None,
    case_ids: list[str] | None = None,
) -> EvalSummary:
    """Run the regression cases through the pipeline and return the results.

    Creates stub ExtractionInputs from each eval case and runs the full pipeline
    in sequence. Each result is compared with the case's expected label and
    score range.

    Args:
        pipeline: Optional pre-configured pipeline instance. If not provided,
            a default pipeline is created with ``persist_claims=False`` and
            ``persist_traces=False`` to avoid polluting the production database.
        case_ids: Optional list of case IDs to run. If None, runs all 20 cases.

    Returns:
        An :py:class:`EvalSummary` with match rates and per-case results.
    """
    cases_to_run = [c for c in GOLDEN_DATASET if case_ids is None or c.case_id in case_ids]

    if pipeline is None:
        pipeline = Pipeline(config=PipelineConfig(persist_claims=False, persist_traces=False))

    logger.info(
        f"Starting eval run: {len(cases_to_run)} case(s)",
        extra={"operation": "eval_start"},
    )

    results: list[EvalResult] = []
    total_tokens = 0

    for case in cases_to_run:
        result = await _run_eval_case(pipeline, case)
        results.append(result)
        if result.tokens_used:
            total_tokens += result.tokens_used

        status = "PASS" if result.passed else ("ERROR" if result.error else "FAIL")
        logger.info(
            f"Eval case {case.case_id}: {status}",
            extra={
                "operation": "eval_case_complete",
                "verdict_correct": result.verdict_correct,
                "score_in_range": result.score_in_range,
            },
        )

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed and not r.error)
    errors = sum(1 for r in results if r.error)
    verdict_correct = sum(1 for r in results if r.verdict_correct)
    score_in_range = sum(1 for r in results if r.score_in_range)
    avg_duration = sum(r.duration_ms for r in results) / len(results) if results else 0.0

    tier1_pairs = [
        (r, c) for r, c in zip(results, cases_to_run, strict=True) if c.tier == "must_pass"
    ]
    tier1_passed = sum(1 for r, _ in tier1_pairs if r.passed)
    tier1_rate = tier1_passed / len(tier1_pairs) if tier1_pairs else 0.0

    summary = EvalSummary(
        total_cases=len(results),
        passed=passed,
        failed=failed,
        errors=errors,
        verdict_accuracy=verdict_correct / len(results) if results else 0.0,
        score_accuracy=score_in_range / len(results) if results else 0.0,
        overall_pass_rate=passed / len(results) if results else 0.0,
        tier1_pass_rate=tier1_rate,
        avg_duration_ms=avg_duration,
        total_tokens_used=total_tokens,
        cases=cases_to_run,
        results=results,
    )

    logger.info(
        f"Eval complete: {passed}/{len(results)} passed ({summary.overall_pass_rate:.1%})",
        extra={
            "operation": "eval_complete",
            "overall_pass_rate": summary.overall_pass_rate,
        },
    )

    return summary


async def _run_eval_case(pipeline: Pipeline, case: EvalCase) -> EvalResult:
    """Run a single eval case and return the result.

    Args:
        pipeline: The pipeline to run the case through.
        case: The eval case to run.

    Returns:
        An :py:class:`EvalResult` for this case.
    """
    start_mono = time.monotonic()

    extraction_input = ExtractionInput(
        trace_id=uuid.uuid4(),
        company_id=case.company_id,
        source_url=case.source_url,
        source_type=case.source_type,
        raw_content=(
            f"Company: {case.company_name}\nCountry: {case.company_country}\n\n{case.claim_text}"
        ),
    )

    try:
        pipeline_results = await pipeline.run_from_document(extraction_input)

        if not pipeline_results:
            duration_ms = int((time.monotonic() - start_mono) * 1000)
            return EvalResult(
                case_id=case.case_id,
                verdict_correct=False,
                score_in_range=False,
                actual_verdict=None,
                actual_score=None,
                duration_ms=duration_ms,
                tokens_used=0,
                error="Pipeline produced no results (no claims extracted)",
            )

        # Take the first result (eval cases contain a single claim)
        result = pipeline_results[0]
        actual_verdict = result.score.verdict
        actual_score = result.score.score

        tokens_used = sum(t.tokens_used or 0 for t in result.traces if t.tokens_used)

        verdict_correct = actual_verdict == case.expected_verdict
        score_in_range = case.expected_score_min <= actual_score <= case.expected_score_max
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        return EvalResult(
            case_id=case.case_id,
            verdict_correct=verdict_correct,
            score_in_range=score_in_range,
            actual_verdict=actual_verdict,
            actual_score=actual_score,
            duration_ms=duration_ms,
            tokens_used=tokens_used,
        )

    except Exception as exc:
        duration_ms = int((time.monotonic() - start_mono) * 1000)
        logger.error(
            f"Eval case {case.case_id} raised exception: {exc}",
            exc_info=True,
            extra={"operation": "eval_case_error", "error_type": type(exc).__name__},
        )
        return EvalResult(
            case_id=case.case_id,
            verdict_correct=False,
            score_in_range=False,
            actual_verdict=None,
            actual_score=None,
            duration_ms=duration_ms,
            tokens_used=0,
            error=f"{type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# Quick-run subset: five cases
# ---------------------------------------------------------------------------

QUICK_CASES: list[str] = [
    "GW-001",  # CONFIRMED_GREENWASHING (version 1 label): Ryanair (ASA ruling of 2020 on a related claim)
    "GW-004",  # LIKELY_GREENWASHING (version 1 label): Eni (AGCM decision of 2019 on Eni Diesel+, annulled in 2024)
    "GW-009",  # LIKELY_GREENWASHING (version 1 label): HSBC (ASA ruling of 2022 on a different claim)
    "GW-010",  # LIKELY_GREENWASHING (version 1 label, known_limitation): Ørsted
    "GW-014",  # CONFIRMED_GREENWASHING (version 1 label): Glencore (no enforcement record)
]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run the golden dataset eval from the command line.

    Usage:
        python -m eval.golden_dataset                   # all 20 cases
        python -m eval.golden_dataset --quick           # 5-case subset
        python -m eval.golden_dataset GW-001 GW-002     # specific cases
    """
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()

    setup_logging(level="INFO")

    args = sys.argv[1:]
    if args == ["--quick"]:
        case_ids: list[str] | None = QUICK_CASES
    elif args:
        case_ids = args
    else:
        case_ids = None

    summary = asyncio.run(run_eval(case_ids=case_ids))
    print(summary.report())

    if step_summary_path := os.getenv("GITHUB_STEP_SUMMARY"):
        from pathlib import Path

        with Path(step_summary_path).open("a") as _f:
            _f.write(f"```\n{summary.report()}\n```\n")

    if os.getenv("GITHUB_ACTIONS"):
        level = "notice" if summary.tier1_pass_rate >= 0.80 else "error"
        print(
            f"::{level} title=Eval Results::"
            f"Tier-1: {summary.tier1_pass_rate:.1%} | "
            f"Overall: {summary.overall_pass_rate:.1%} | "
            f"{summary.passed}/{summary.total_cases} passed"
        )

    sys.exit(0 if summary.overall_pass_rate >= 0.80 else 1)

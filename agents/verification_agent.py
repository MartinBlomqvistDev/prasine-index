"""Verification Agent for the Prasine Index pipeline.

Queries 21 independent data sources in parallel and aggregates results into a
VerificationResult passed to the Judge Agent.

Sources queried:
  Regulatory/verified emissions:
    EU ETS/EUTL, E-PRTR, Climate TRACE, EDGAR (JRC), EEA National, Eurostat
  Infrastructure expansion:
    GCPT (coal plants), EGT (Europe gas), GOGET (O&G extraction),
    GOGEL (O&G companies), GCEL (coal companies)
  Ratings and benchmarks:
    SBTi, CA100+, TPI, InfluenceMap, CDP
  Finance and lobbying:
    Banking on Climate Chaos, EU Transparency Register, EUR-Lex
  Enforcement and public funding:
    Enforcement rulings, EU Innovation Fund

This is the one agent in the pipeline that uses LangGraph for orchestration:
the parallel fan-out to independent external APIs, combined with per-source
isolation and the need to aggregate partial results when one or more sources
fail, is exactly the class of problem that benefits from a state machine
framework.
"""

from __future__ import annotations

import operator
import time
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from core.logger import bind_trace_context, get_logger
from core.retry import DataSourceError, agent_error_boundary
from ingest.ca100 import fetch_ca100_data
from ingest.cdp import fetch_cdp_data
from ingest.climate_trace import fetch_climate_trace_data
from ingest.coal_exit import fetch_coal_exit_data
from ingest.edgar import fetch_edgar_data
from ingest.eea_national import fetch_eea_national_data
from ingest.egt import fetch_egt_data
from ingest.enforcement import fetch_enforcement_data
from ingest.eprtr import fetch_eprtr_data
from ingest.eu_ets import fetch_eu_ets_data
from ingest.eu_innovation_fund import fetch_eu_innovation_fund_data
from ingest.eu_transparency_register import fetch_eu_transparency_register_data
from ingest.eurlex import fetch_eurlex_data
from ingest.eurostat import fetch_eurostat_data
from ingest.fossil_finance import fetch_fossil_finance_data
from ingest.gcpt import fetch_gcpt_data
from ingest.gogel import fetch_gogel_data
from ingest.goget import fetch_goget_data
from ingest.influence_map import fetch_influence_map_data
from ingest.sbti import fetch_sbti_data
from ingest.tpi import fetch_tpi_data
from models.claim import Claim
from models.company import CompanyContext
from models.evidence import Evidence, EvidenceSource, VerificationResult
from models.trace import AgentName, AgentOutcome, AgentTrace

__all__ = [
    "VerificationAgent",
    "VerificationInput",
]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------


class VerificationState(TypedDict):
    """Mutable state threaded through the LangGraph verification graph.

    The ``evidence`` and ``data_gaps`` fields use ``Annotated`` with
    ``operator.add`` as the reducer. This means each parallel fetch node
    returns a partial list, and LangGraph's runtime merges all partial lists
    via concatenation — no node needs to know what the others returned.

    Attributes:
        claim: The claim under verification. Read-only across all nodes.
        context: Company context assembled by the Context Agent. Read-only.
        evidence: Evidence records accumulated across all fetch nodes.
            Each node appends its own records; LangGraph merges via operator.add.
        data_gaps: Source identifiers for which data retrieval failed.
            Each node appends its own failures; LangGraph merges via operator.add.
    """

    claim: Claim
    context: CompanyContext
    evidence: Annotated[list[Evidence], operator.add]
    data_gaps: Annotated[list[str], operator.add]


# ---------------------------------------------------------------------------
# I/O models
# ---------------------------------------------------------------------------


class VerificationInput(BaseModel):
    """Input contract for the Verification Agent.

    Produced by the pipeline orchestrator after the Context Agent completes.

    Attributes:
        claim: The claim to verify.
        context: Company context assembled by the Context Agent.
    """

    model_config = ConfigDict(from_attributes=True)

    claim: Claim = Field(..., description="The claim to verify against EU open data sources.")
    context: CompanyContext = Field(
        ..., description="Company context assembled by the Context Agent."
    )


# ---------------------------------------------------------------------------
# Graph node functions
# ---------------------------------------------------------------------------


async def _node_fetch_eu_ets(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch verified emissions data from the EU ETS EUTL.

    Queries the European Union Transaction Log for verified annual emissions
    data for all EU ETS installation IDs registered against this company.
    Returns partial state containing either the evidence record or a data gap
    entry if the upstream source is unavailable.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]
    installation_ids = context.company.eu_ets_installation_ids

    if not installation_ids:
        logger.info(
            "EU ETS fetch skipped: no installation IDs registered for company",
            extra={"operation": "fetch_eu_ets_skipped"},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EU_ETS}: no installation IDs registered"],
        }

    try:
        evidence = await fetch_eu_ets_data(
            claim=claim,
            installation_ids=installation_ids,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"EU ETS fetch failed: {exc.message}",
            extra={
                "operation": "fetch_eu_ets_failed",
                "error_type": type(exc).__name__,
                "http_status": exc.status_code,
                "source": EvidenceSource.EU_ETS.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EU_ETS}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"EU ETS fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eu_ets_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EU_ETS}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_cdp(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch self-reported climate data from the CDP open dataset.

    Queries the CDP (formerly Carbon Disclosure Project) open data export for
    the company's self-reported emissions, targets, and climate governance data.
    CDP data is self-reported and weighted accordingly by the Judge Agent.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_cdp_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"CDP fetch failed: {exc.message}",
            extra={
                "operation": "fetch_cdp_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.CDP.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.CDP}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"CDP fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_cdp_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.CDP}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_eurlex(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch legislative and CSRD context from EUR-Lex.

    Queries the EUR-Lex REST API for CSRD disclosure records, Green Claims
    Directive references, and any legislative proceedings relevant to the
    claim's subject matter. Legislative records provide the regulatory
    framework within which claims are assessed.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eurlex_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"EUR-Lex fetch failed: {exc.message}",
            extra={
                "operation": "fetch_eurlex_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.EUR_LEX.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EUR_LEX}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"EUR-Lex fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eurlex_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EUR_LEX}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_sbti(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch SBTi target validation data from the local bulk dataset.

    Queries the Science Based Targets initiative Companies Taking Action dataset
    for validated, committed, or removed near-term and net-zero targets. A removed
    target while the company continues to claim science-based alignment is a direct
    CONFIRMED_GREENWASHING indicator and is given high confidence.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_sbti_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"SBTi fetch failed: {exc.message}",
            extra={
                "operation": "fetch_sbti_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.SBTI.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.SBTI}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"SBTi fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_sbti_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.SBTI}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_eprtr(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch E-PRTR non-CO2 GHG release data from the local bulk dataset.

    Queries the EEA European Pollutant Release and Transfer Register for the
    company's non-CO2 GHG releases to air (CH4, N2O, HFCs, etc.). This data
    complements EU ETS verified CO2 figures and catches industrial emissions
    not covered by the EU carbon market. Rising non-CO2 GHGs while claiming
    environmental leadership directly contradicts that claim.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eprtr_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"E-PRTR fetch failed: {exc.message}",
            extra={
                "operation": "fetch_eprtr_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.EPRTR.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EPRTR}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"E-PRTR fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eprtr_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EPRTR}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_ca100(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch CA100+ net-zero benchmark assessment.

    Queries the Climate Action 100+ company benchmark, the world's largest
    investor-led assessment of the 170 highest-emitting listed companies.
    A company claiming net-zero ambition while rated "Not Aligned" by CA100+
    is contradicted by the consensus of 700+ investors representing $68tn AUM.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]
    try:
        evidence = await fetch_ca100_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}
    except Exception as exc:
        logger.error(
            f"CA100+ fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_ca100_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.CA100}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_fossil_finance(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Banking on Climate Chaos fossil financing record.

    Queries the fossil fuel financing database for banks and financial institutions.
    A bank providing hundreds of billions in fossil fuel financing while making
    net-zero or climate-positive claims is the canonical financial sector greenwashing
    pattern — exemplified by the landmark ASA 2022 HSBC ruling.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]
    try:
        evidence = await fetch_fossil_finance_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}
    except Exception as exc:
        logger.error(
            f"Fossil finance fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_fossil_finance_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [
                f"{EvidenceSource.FOSSIL_FINANCE}: unexpected error — {type(exc).__name__}"
            ],
        }


async def _node_fetch_coal_exit(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: check the Urgewald Global Coal Exit List (GCEL).

    Queries the GCEL for companies actively expanding coal capacity.
    A company listed as a coal expander while claiming a clean-energy
    transition or Paris-aligned strategy is a documented greenwashing case.
    The GCEL is the standard coal screen used by 400+ financial institutions.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]
    try:
        evidence = await fetch_coal_exit_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}
    except Exception as exc:
        logger.error(
            f"GCEL fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_coal_exit_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.COAL_EXIT}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_enforcement(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: look up national and EU enforcement rulings for the company.

    Queries the static enforcement rulings database for confirmed bans, fines,
    misleading-claim rulings, and active investigations from ASA, ACM, AGCM, CMA,
    courts, and the European Commission. A confirmed ruling from a regulator is the
    strongest possible evidence — it means an authority has already independently
    determined that the company's green claims were unsubstantiated.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_enforcement_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"Enforcement lookup raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_enforcement_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.ENFORCEMENT}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_influence_map(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch InfluenceMap climate lobbying scores from the local dataset.

    Queries the InfluenceMap Company Climate Policy Engagement database for the
    company's lobbying alignment score (A+ to F). A company scoring in the
    obstructive range (D/E/F) while making green claims is a primary greenwashing
    indicator — its lobbying activity actively undermines the climate policies it
    publicly claims to support.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_influence_map_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except DataSourceError as exc:
        logger.warning(
            f"InfluenceMap fetch failed: {exc.message}",
            extra={
                "operation": "fetch_influencemap_failed",
                "error_type": type(exc).__name__,
                "source": EvidenceSource.INFLUENCE_MAP.value,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.INFLUENCE_MAP}: {exc.message}"],
        }
    except Exception as exc:
        logger.error(
            f"InfluenceMap fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_influencemap_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [
                f"{EvidenceSource.INFLUENCE_MAP}: unexpected error — {type(exc).__name__}"
            ],
        }


async def _node_fetch_eu_innovation_fund(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch EU Innovation Fund grant data.

    Queries the local EU Innovation Fund projects CSV for grants awarded to
    this company. An Innovation Fund grant indicates independent EC technical
    evaluation — partially mitigating evidence for CCS and clean-tech claims.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eu_innovation_fund_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"EU Innovation Fund fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={
                "operation": "fetch_eu_innovation_fund_error",
                "error_type": type(exc).__name__,
            },
        )
        return {
            "evidence": [],
            "data_gaps": [
                f"{EvidenceSource.EU_INNOVATION_FUND}: unexpected error — {type(exc).__name__}"
            ],
        }


async def _node_fetch_gogel(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Global Oil and Gas Exit List data.

    Queries the local GOGEL CSV for oil and gas expansion data. A company
    actively expanding upstream oil and gas while claiming clean-energy
    transition or Paris alignment is a documented greenwashing signal.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_gogel_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"GOGEL fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_gogel_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.GOGEL}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_eurostat(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Eurostat GHG sector breakdown for the company's country.

    Queries the Eurostat env_air_gge dataset for national and sector-level GHG
    totals. Provides official EU statistics context for validating sector-proportion
    and national-benchmark claims.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eurostat_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"Eurostat fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eurostat_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EUROSTAT}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_eu_transparency_register(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch EU Transparency Register lobbying registration.

    Checks whether the company is registered as an EU lobbyist. Combined with
    InfluenceMap positions, this allows the Judge Agent to detect companies that
    lobby against climate policy while making green claims publicly.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eu_transparency_register_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"EU TR fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eu_tr_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [
                f"{EvidenceSource.EU_TRANSPARENCY_REGISTER}: unexpected error — {type(exc).__name__}"
            ],
        }


async def _node_fetch_eea_national(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch EEA national GHG emissions context.

    Queries the EEA national emissions inventory to provide country-level
    baseline data. Used to validate country-proportion claims and to give
    the Judge Agent context on the national emissions trajectory.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_eea_national_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"EEA national fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_eea_national_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [
                f"{EvidenceSource.EEA_NATIONAL}: unexpected error — {type(exc).__name__}"
            ],
        }


async def _node_fetch_edgar(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch EDGAR JRC national GHG totals and sector breakdown.

    Queries the JRC EDGAR 2025 dataset for the company's country. Provides
    the most recent (2024) independent national GHG estimate as context for
    validating sector-proportion and national-benchmark claims.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_edgar_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"EDGAR fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_edgar_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EDGAR}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_egt(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Europe Gas Tracker infrastructure data.

    Checks whether the company owns European gas pipelines, LNG terminals, or
    gas plants in active development. Expanding European gas infrastructure
    contradicts fossil gas phase-out or net-zero transition claims.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_egt_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"EGT fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_egt_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.EGT}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_goget(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Global Oil and Gas Extraction Tracker data.

    Checks whether the company owns O&G extraction fields in active development.
    FID on a new field means capital committed to decades of upstream fossil
    fuel production — directly contradicts net-zero or phase-out claims.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_goget_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"GOGET fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_goget_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.GOGET}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_gcpt(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Global Coal Plant Tracker facility data.

    Checks whether the company owns coal units in active development
    (Announced through Construction). A company expanding coal capacity
    while claiming clean-energy transition is directly contradicted.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_gcpt_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"GCPT fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_gcpt_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.GCPT}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_tpi(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch TPI Management Quality and Carbon Performance assessment.

    Queries the TPI dataset for the company's MQ level and CP pathway alignment.
    A "Not Aligned" 2050 trajectory while claiming net-zero contradicts the claim
    based on the consensus assessment of 150+ investors ($80tn AUM).

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_tpi_data(claim=claim, company=context.company)
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"TPI fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_tpi_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [f"{EvidenceSource.TPI}: unexpected error — {type(exc).__name__}"],
        }


async def _node_fetch_climate_trace(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: fetch Climate TRACE independent emissions estimates.

    Queries the Climate TRACE v7 API for satellite/ML-derived emissions
    estimates independent of company self-reporting. A significant discrepancy
    between Climate TRACE facility estimates and company-disclosed figures is a
    primary greenwashing signal — one of the few sources that can contradict a
    company's own disclosure with independent evidence.

    Args:
        state: Current verification graph state.

    Returns:
        Partial state dict with ``evidence`` and ``data_gaps`` keys.
    """
    claim = state["claim"]
    context = state["context"]

    try:
        evidence = await fetch_climate_trace_data(
            claim=claim,
            company=context.company,
        )
        return {"evidence": evidence, "data_gaps": []}

    except Exception as exc:
        logger.error(
            f"Climate TRACE fetch raised unexpected exception: {exc}",
            exc_info=True,
            extra={"operation": "fetch_climate_trace_error", "error_type": type(exc).__name__},
        )
        return {
            "evidence": [],
            "data_gaps": [
                f"{EvidenceSource.CLIMATE_TRACE}: unexpected error — {type(exc).__name__}"
            ],
        }


async def _node_aggregate(state: VerificationState) -> dict[str, Any]:
    """LangGraph node: synthesise all evidence into an overall assessment.

    Runs after all parallel fetch nodes have completed. Receives the fully
    merged ``evidence`` and ``data_gaps`` lists and produces an
    ``overall_assessment`` string summarising what the collected evidence
    shows in aggregate. This summary is provided as context to the Judge
    Agent alongside the individual evidence records.

    The aggregate node does not call an LLM — the summary is constructed
    programmatically from the evidence records to keep this step fast and
    deterministic. The Judge Agent has the LLM reasoning step.

    Args:
        state: Final verification graph state with all evidence merged.

    Returns:
        Partial state dict (no-op; the state is complete at this point).
        The :py:class:`VerificationAgent` reads the final state directly
        to construct the :py:class:`~models.evidence.VerificationResult`.
    """
    evidence = state["evidence"]
    data_gaps = state["data_gaps"]

    supporting = sum(1 for e in evidence if e.supports_claim is True)
    contradicting = sum(1 for e in evidence if e.supports_claim is False)
    inconclusive = sum(1 for e in evidence if e.supports_claim is None)

    logger.info(
        f"Evidence aggregation complete: {len(evidence)} record(s) — "
        f"{supporting} supporting, {contradicting} contradicting, "
        f"{inconclusive} inconclusive; {len(data_gaps)} data gap(s)",
        extra={
            "operation": "verification_aggregate",
            "outcome": AgentOutcome.SUCCESS.value if evidence else AgentOutcome.PARTIAL.value,
        },
    )

    # No state mutation needed — the agent reads the final state post-graph
    return {}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _build_verification_graph() -> StateGraph[VerificationState]:
    """Construct the LangGraph StateGraph for parallel source verification.

    The graph fans out from START to six independent fetch nodes, each
    querying a different open data source. All six nodes converge at
    the ``aggregate`` node before reaching END.

    Because each fetch node returns a *partial* state update to the
    ``evidence`` and ``data_gaps`` lists (using ``operator.add`` reducers),
    LangGraph merges the partial results automatically as the parallel
    branches complete. No explicit synchronisation is required.

                                         START
        ↙  ↙  ↙  ↓  ↓  ↓  ↓  ↘  ↘  ↘  ↘  ↘  ↘  ↘  ↘
    ETS CDP SBTI EPRTR IM ENF CA100 FF GCEL EUR-LEX EIF GOGEL EEA EUTR ESTAT CT
        ↘  ↘  ↘  ↓  ↓  ↓  ↓  ↙  ↙  ↙  ↙  ↙  ↙  ↙  ↙
                        aggregate
                            ↓
                           END

    Returns:
        An uncompiled :py:class:`~langgraph.graph.StateGraph` instance.
    """
    graph = StateGraph(VerificationState)

    graph.add_node("fetch_eu_ets", _node_fetch_eu_ets)
    graph.add_node("fetch_cdp", _node_fetch_cdp)
    graph.add_node("fetch_sbti", _node_fetch_sbti)
    graph.add_node("fetch_eprtr", _node_fetch_eprtr)
    graph.add_node("fetch_influence_map", _node_fetch_influence_map)
    graph.add_node("fetch_enforcement", _node_fetch_enforcement)
    graph.add_node("fetch_ca100", _node_fetch_ca100)
    graph.add_node("fetch_fossil_finance", _node_fetch_fossil_finance)
    graph.add_node("fetch_coal_exit", _node_fetch_coal_exit)
    graph.add_node("fetch_eurlex", _node_fetch_eurlex)
    graph.add_node("fetch_eu_innovation_fund", _node_fetch_eu_innovation_fund)
    graph.add_node("fetch_gogel", _node_fetch_gogel)
    graph.add_node("fetch_eea_national", _node_fetch_eea_national)
    graph.add_node("fetch_eu_transparency_register", _node_fetch_eu_transparency_register)
    graph.add_node("fetch_eurostat", _node_fetch_eurostat)
    graph.add_node("fetch_climate_trace", _node_fetch_climate_trace)
    graph.add_node("fetch_tpi", _node_fetch_tpi)
    graph.add_node("fetch_gcpt", _node_fetch_gcpt)
    graph.add_node("fetch_egt", _node_fetch_egt)
    graph.add_node("fetch_goget", _node_fetch_goget)
    graph.add_node("fetch_edgar", _node_fetch_edgar)
    graph.add_node("aggregate", _node_aggregate)

    # Fan out from START to all fetch nodes — LangGraph runs these in parallel
    graph.add_edge(START, "fetch_eu_ets")
    graph.add_edge(START, "fetch_cdp")
    graph.add_edge(START, "fetch_sbti")
    graph.add_edge(START, "fetch_eprtr")
    graph.add_edge(START, "fetch_influence_map")
    graph.add_edge(START, "fetch_enforcement")
    graph.add_edge(START, "fetch_ca100")
    graph.add_edge(START, "fetch_fossil_finance")
    graph.add_edge(START, "fetch_coal_exit")
    graph.add_edge(START, "fetch_eurlex")
    graph.add_edge(START, "fetch_eu_innovation_fund")
    graph.add_edge(START, "fetch_gogel")
    graph.add_edge(START, "fetch_eea_national")
    graph.add_edge(START, "fetch_eu_transparency_register")
    graph.add_edge(START, "fetch_eurostat")
    graph.add_edge(START, "fetch_climate_trace")
    graph.add_edge(START, "fetch_tpi")
    graph.add_edge(START, "fetch_gcpt")
    graph.add_edge(START, "fetch_egt")
    graph.add_edge(START, "fetch_goget")
    graph.add_edge(START, "fetch_edgar")

    # All fetch nodes converge at aggregate
    graph.add_edge("fetch_eu_ets", "aggregate")
    graph.add_edge("fetch_cdp", "aggregate")
    graph.add_edge("fetch_sbti", "aggregate")
    graph.add_edge("fetch_eprtr", "aggregate")
    graph.add_edge("fetch_influence_map", "aggregate")
    graph.add_edge("fetch_enforcement", "aggregate")
    graph.add_edge("fetch_ca100", "aggregate")
    graph.add_edge("fetch_fossil_finance", "aggregate")
    graph.add_edge("fetch_coal_exit", "aggregate")
    graph.add_edge("fetch_eurlex", "aggregate")
    graph.add_edge("fetch_eu_innovation_fund", "aggregate")
    graph.add_edge("fetch_gogel", "aggregate")
    graph.add_edge("fetch_eea_national", "aggregate")
    graph.add_edge("fetch_eu_transparency_register", "aggregate")
    graph.add_edge("fetch_eurostat", "aggregate")
    graph.add_edge("fetch_climate_trace", "aggregate")
    graph.add_edge("fetch_tpi", "aggregate")
    graph.add_edge("fetch_gcpt", "aggregate")
    graph.add_edge("fetch_egt", "aggregate")
    graph.add_edge("fetch_goget", "aggregate")
    graph.add_edge("fetch_edgar", "aggregate")

    graph.add_edge("aggregate", END)

    return graph


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class VerificationAgent:
    """Verifies green claims against EU open data sources using a LangGraph graph.

    Orchestrates parallel queries to EU ETS, CDP, and EUR-Lex via a
    LangGraph StateGraph where each data source is a dedicated node. The
    fan-out topology ensures all sources are queried concurrently; the
    ``operator.add`` reducer on the ``evidence`` list merges partial results
    as each node completes.

    LangGraph is used here — and only here in the pipeline — because this
    agent has exactly the characteristics that benefit from a framework:
    multiple independent tools, parallel execution, partial-failure tolerance,
    and state that accumulates across branches. The other agents are
    single-step LLM calls or pure database queries where a framework adds
    indirection without value.

    Attributes:
        _graph: The compiled LangGraph state graph.
    """

    def __init__(self) -> None:
        """Initialise the Verification Agent and compile the LangGraph graph.

        The graph is compiled once at agent construction time. Compilation
        is a synchronous operation that validates the graph topology and
        produces the runnable object used for all subsequent invocations.
        """
        self._graph = _build_verification_graph().compile()
        logger.info(
            "Verification graph compiled",
            extra={"operation": "verification_graph_compiled"},
        )

    async def run(self, input: VerificationInput) -> tuple[VerificationResult, AgentTrace]:
        """Run the parallel verification graph for the given claim.

        Invokes the compiled LangGraph graph with the initial state derived
        from the input, then reads the final merged state to construct a
        :py:class:`~models.evidence.VerificationResult`.

        Args:
            input: Validated verification input containing the claim and
                company context.

        Returns:
            A tuple of:
            - :py:class:`~models.evidence.VerificationResult`: All gathered
              evidence and the aggregate assessment narrative.
            - :py:class:`~models.trace.AgentTrace`: Execution trace for this
              agent step.
        """
        bind_trace_context(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent_name=AgentName.VERIFICATION.value,
        )
        started_at = datetime.now(UTC)
        start_mono = time.monotonic()

        logger.info(
            "Verification started",
            extra={
                "operation": "verification_start",
                "company_id": str(input.context.company.id),
            },
        )

        result: VerificationResult | None = None
        outcome = AgentOutcome.SUCCESS

        async with agent_error_boundary(agent=AgentName.VERIFICATION.value, operation="run"):
            initial_state: VerificationState = {
                "claim": input.claim,
                "context": input.context,
                "evidence": [],
                "data_gaps": [],
            }

            final_state = cast("VerificationState", await self._graph.ainvoke(initial_state))

            evidence = final_state["evidence"]
            data_gaps = final_state["data_gaps"]

            if not evidence or data_gaps:
                outcome = AgentOutcome.PARTIAL

            overall_assessment = _build_assessment_summary(evidence, data_gaps)

            # Derive sources_queried from evidence that arrived + data_gaps that
            # mention a source name. This is honest: if EU ETS was skipped because
            # the company has no registered installations, it won't appear here.
            sources_with_evidence = {ev.source.value for ev in evidence}
            sources_with_gaps = {gap.split(":")[0].strip() for gap in data_gaps}
            sources_queried = sorted(sources_with_evidence | sources_with_gaps)

            result = VerificationResult(
                claim_id=input.claim.id,
                trace_id=input.claim.trace_id,
                evidence=evidence,
                overall_assessment=overall_assessment,
                data_gaps=data_gaps,
                sources_queried=sources_queried,
            )

        completed_at = datetime.now(UTC)
        duration_ms = int((time.monotonic() - start_mono) * 1000)

        trace = AgentTrace(
            trace_id=input.claim.trace_id,
            claim_id=input.claim.id,
            agent=AgentName.VERIFICATION,
            outcome=outcome,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            input_schema="agents.verification_agent.VerificationInput",
            output_schema="models.evidence.VerificationResult",
            metadata={
                "evidence_count": len(result.evidence) if result else 0,
                "data_gap_count": len(result.data_gaps) if result else 0,
                "sources_queried": [
                    "EU_ETS",
                    "CDP",
                    "SBTI",
                    "EPRTR",
                    "INFLUENCE_MAP",
                    "ENFORCEMENT",
                    "CA100",
                    "FOSSIL_FINANCE",
                    "COAL_EXIT",
                    "EUR_LEX",
                    "EU_INNOVATION_FUND",
                    "GOGEL",
                    "EEA_NATIONAL",
                    "EU_TRANSPARENCY_REGISTER",
                    "EUROSTAT",
                    "CLIMATE_TRACE",
                    "TPI",
                    "GCPT",
                    "EGT",
                    "GOGET",
                    "EDGAR",
                ],
            },
        )

        assert result is not None
        return result, trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_assessment_summary(
    evidence: list[Evidence],
    data_gaps: list[str],
) -> str:
    """Construct a plain-text summary of the aggregated verification evidence.

    Produces a concise, structured summary suitable for inclusion in the
    Judge Agent's context. The summary describes the counts of supporting,
    contradicting, and inconclusive evidence records, and explicitly lists
    any data gaps so the Judge Agent can reflect on missing coverage.

    Args:
        evidence: All evidence records gathered during verification.
        data_gaps: Descriptions of sources that failed or returned no data.

    Returns:
        A plain-text assessment summary string.
    """
    if not evidence and not data_gaps:
        return "No evidence was gathered and no data sources were queried."

    supporting = [e for e in evidence if e.supports_claim is True]
    contradicting = [e for e in evidence if e.supports_claim is False]
    inconclusive = [e for e in evidence if e.supports_claim is None]

    lines: list[str] = [
        f"Verification retrieved {len(evidence)} evidence record(s) from "
        f"{len({e.source for e in evidence})} source(s).",
        f"  Supporting the claim:    {len(supporting)}",
        f"  Contradicting the claim: {len(contradicting)}",
        f"  Inconclusive:            {len(inconclusive)}",
    ]

    if contradicting:
        lines.append("Contradicting evidence summaries:")
        for e in contradicting:
            lines.append(f"  - [{e.source.value}] {e.summary}")

    if data_gaps:
        lines.append(f"{len(data_gaps)} data source(s) were unavailable:")
        for gap in data_gaps:
            lines.append(f"  - {gap}")

    return "\n".join(lines)

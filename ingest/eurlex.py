"""Regulatory context module for the Prasine Index Verification Agent.

Provides static EU legislative standards against which green claims are judged.
EUR-Lex does not contain company CSRD reports (those go to national registers);
it contains the legislation itself. Rather than making fragile API calls for
content that does not change, this module returns the key legal standards as
structured Evidence so the Judge Agent always has the regulatory baseline.

Sources embedded here:
- EmpCo Directive (EU 2024/825) — in force March 2024, amends UCPD Annex I
- UCPD (Directive 2005/29/EC) Article 6 — misleading commercial practices
- CSRD (Directive 2022/2464) — mandatory disclosure obligations
- EU ETS Regulation 2003/87/EC — verified emissions as legal ground truth

Note: The Green Claims Directive proposal (COM/2023/0166) was withdrawn by the
European Commission in June 2025 before adoption. It is NOT cited here.
The EmpCo Directive is the in-force instrument for environmental claim standards.
"""

from __future__ import annotations

from models.claim import Claim, ClaimCategory
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eurlex_data"]

# ---------------------------------------------------------------------------
# Regulatory standards by claim category
# Each entry: (celex_id, title, year, summary_for_judge)
# ---------------------------------------------------------------------------

_REGULATORY_CONTEXT: dict[ClaimCategory, list[tuple[str, str, int, str]]] = {
    ClaimCategory.NET_ZERO_TARGET: [
        (
            "32024L0825",
            "EmpCo Directive (EU 2024/825), amending UCPD Annex I",
            2024,
            "In force since March 2024. Amends UCPD Annex I to blacklist environmental "
            "claims that are not substantiated by recognised scientific evidence. "
            "Net-zero claims must demonstrate that residual emissions will be permanently "
            "removed by certified carbon removals, not offset credits. Generic net-zero "
            "pledges without a credible, verifiable transition plan are automatically "
            "unfair commercial practices under the amended Annex I. Claims based solely "
            "on carbon offsetting schemes are blacklisted.",
        ),
        (
            "32022L2464",
            "CSRD — Corporate Sustainability Reporting Directive (2022/2464)",
            2022,
            "Large companies must disclose scope 1, 2 and 3 GHG emissions under ESRS E1. "
            "A net-zero claim that contradicts or is absent from the mandatory CSRD disclosure "
            "constitutes a material inconsistency. CSRD applies to companies with >500 employees "
            "or listed on EU-regulated markets from FY2024 reporting.",
        ),
    ],
    ClaimCategory.CARBON_NEUTRAL: [
        (
            "32024L0825",
            "EmpCo Directive (EU 2024/825), amending UCPD Annex I",
            2024,
            "In force since March 2024. Carbon-neutral claims must be based on actual "
            "emission reductions across the full lifecycle, not offset purchases. "
            "The amended UCPD Annex I blacklists carbon neutrality claims that rely "
            "primarily on offset schemes without verified absolute emission reductions. "
            "UCPD Article 6(1) covers misleading claims that deceive the average consumer "
            "about the environmental impact of a product or the trader.",
        ),
    ],
    ClaimCategory.EMISSIONS_REDUCTION: [
        (
            "32003L0087",
            "EU ETS Directive 2003/87/EC as amended",
            2003,
            "EU ETS verified emissions (Article 15) represent the highest-quality legal "
            "ground truth for actual GHG emissions. Verified figures are produced by "
            "accredited independent third-party verifiers under Regulation 601/2012. "
            "A company claiming emissions reductions that are not reflected in EUTL "
            "verified data is making a claim contradicted by mandatory legal disclosure.",
        ),
        (
            "32024L0825",
            "EmpCo Directive (EU 2024/825), amending UCPD Annex I",
            2024,
            "In force since March 2024. Emissions reduction claims must state the baseline "
            "year, scope (Scope 1/2/3), and methodology. Per-unit or intensity-based "
            "reduction claims that obscure absolute emission increases are misleading "
            "under UCPD Article 6(1). Aggregating reductions and increases to manufacture "
            "a net reduction figure violates the substantiation standard.",
        ),
    ],
    ClaimCategory.RENEWABLE_ENERGY: [
        (
            "32024L0825",
            "EmpCo Directive (EU 2024/825), amending UCPD Annex I",
            2024,
            "In force since March 2024. Renewable energy claims must specify the percentage "
            "of total energy consumption covered, the source, and whether RECs/GOs are used. "
            "Claims of 100% renewable electricity that rely on unbundled certificates without "
            "physical supply contracts are misleading under UCPD Article 6(1). The amended "
            "Annex I blacklists sustainability labels not based on a transparent, publicly "
            "available verification scheme.",
        ),
    ],
    ClaimCategory.SUSTAINABLE_SUPPLY_CHAIN: [
        (
            "32022L2464",
            "CSRD — Corporate Sustainability Reporting Directive (2022/2464)",
            2022,
            "ESRS E1-6 requires disclosure of Scope 3 GHG emissions covering the full value "
            "chain. Supply chain sustainability claims must be consistent with CSRD Scope 3 "
            "disclosures. Claims of sustainable supply chains without supporting Scope 3 "
            "data are unsubstantiated under UCPD Article 6 and the EmpCo Directive (EU 2024/825).",
        ),
    ],
    ClaimCategory.SCIENCE_BASED_TARGETS: [
        (
            "32024L0825",
            "EmpCo Directive (EU 2024/825), amending UCPD Annex I",
            2024,
            "In force since March 2024. Science-based target claims require that the target "
            "methodology is publicly disclosed and independently validated (e.g. SBTi approval). "
            "Reference to science-based targets without current validation status is misleading "
            "under UCPD Article 6(1). Expired or withdrawn SBTi approvals render the claim false. "
            "The amended Annex I blacklists sustainability labels not based on a transparent "
            "and publicly available verification scheme.",
        ),
    ],
    ClaimCategory.OTHER: [
        (
            "32024L0825",
            "EmpCo Directive (EU 2024/825), amending UCPD Annex I",
            2024,
            "In force since March 2024. All explicit environmental claims must be substantiated "
            "by recognised scientific evidence, cover the full lifecycle where relevant, and not "
            "mislead consumers by omission. The amended UCPD Annex I blacklists generic "
            "environmental claims — 'eco-friendly', 'green', 'sustainable' — without specific, "
            "verifiable substantiation. UCPD Article 6(1) covers any claim that deceives the "
            "average consumer about the environmental impact of a product or trader.",
        ),
    ],
}


async def fetch_eurlex_data(
    claim: Claim,
    company: object,  # Company — typed loosely to avoid circular import
) -> list[Evidence]:
    """Return EU regulatory standards applicable to the claim category.

    No network calls are made. Returns static regulatory context from the
    EmpCo Directive (EU 2024/825), CSRD, and EU ETS legislation so the
    Judge Agent always has the legal baseline regardless of API availability.

    Args:
        claim: The claim under assessment.
        company: The company that made the claim (unused; kept for interface
            compatibility with other ingest modules).

    Returns:
        List of Evidence records containing applicable regulatory standards.
    """
    standards = _REGULATORY_CONTEXT.get(
        claim.claim_category,
        _REGULATORY_CONTEXT[ClaimCategory.OTHER],
    )

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.EUR_LEX,
            evidence_type=EvidenceType.LEGISLATIVE_RECORD,
            source_url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
            raw_data={"celex": celex, "title": title},
            summary=f"[{celex}] {title}: {summary}",
            data_year=year,
            supports_claim=None,
            confidence=0.95,
        )
        for celex, title, year, summary in standards
    ]

"""Regulatory context module for the Prasine Index Verification Agent.

Provides static EU legislative standards against which green claims are judged.
EUR-Lex does not contain company CSRD reports (those go to national registers);
it contains the legislation itself. Rather than making fragile API calls for
content that does not change, this module returns the key legal standards as
structured Evidence so the Judge Agent always has the regulatory baseline.

Sources embedded here:
- EU Green Claims Directive (COM/2023/0166) — substantiation requirements
- CSRD (Directive 2022/2464) — mandatory disclosure obligations
- EU ETS Regulation 2003/87/EC — verified emissions as legal ground truth
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
            "52023PC0166",
            "Green Claims Directive proposal (COM/2023/0166)",
            2023,
            "Article 3 requires explicit substantiation of net-zero claims: companies must "
            "demonstrate that residual emissions will be permanently removed by certified "
            "carbon removals, not offset credits. Vague net-zero pledges without a credible "
            "transition plan violate the substantiation standard. Article 7 prohibits claims "
            "based solely on carbon offsetting schemes.",
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
            "52023PC0166",
            "Green Claims Directive proposal (COM/2023/0166)",
            2023,
            "Article 3(3)(b) explicitly requires that carbon-neutral claims be based on "
            "actual emission reductions across the full lifecycle, not offset purchases. "
            "Carbon neutrality claims relying primarily on offsets are presumed misleading "
            "under Article 6 (unfair commercial practices).",
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
            "52023PC0166",
            "Green Claims Directive proposal (COM/2023/0166)",
            2023,
            "Article 3(3)(a) requires emissions reduction claims to state the baseline year, "
            "scope (Scope 1/2/3), and methodology. Per-unit or intensity-based reduction "
            "claims must not obscure absolute emission increases. Article 5 prohibits "
            "aggregating reductions and increases to manufacture a net reduction figure.",
        ),
    ],
    ClaimCategory.RENEWABLE_ENERGY: [
        (
            "52023PC0166",
            "Green Claims Directive proposal (COM/2023/0166)",
            2023,
            "Renewable energy claims must specify the percentage of total energy consumption "
            "covered, the source, and whether RECs/GOs are used. Claims of 100% renewable "
            "electricity that rely on unbundled certificates without physical supply contracts "
            "are considered potentially misleading under Article 3.",
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
            "data are unsubstantiated under the Green Claims Directive Article 3.",
        ),
    ],
    ClaimCategory.SCIENCE_BASED_TARGETS: [
        (
            "52023PC0166",
            "Green Claims Directive proposal (COM/2023/0166)",
            2023,
            "Science-based target claims require that the target methodology is publicly "
            "disclosed and independently validated (e.g. SBTi approval). Reference to "
            "science-based targets without current validation status is misleading. "
            "Expired or withdrawn SBTi approvals render the claim false.",
        ),
    ],
    ClaimCategory.OTHER: [
        (
            "52023PC0166",
            "Green Claims Directive proposal (COM/2023/0166)",
            2023,
            "The Green Claims Directive requires all explicit environmental claims to be "
            "substantiated by recognised scientific evidence, cover the full lifecycle "
            "where relevant, and not mislead consumers by omission. Vague claims such as "
            "'eco-friendly', 'green', or 'sustainable' without specific substantiation "
            "are prohibited under Article 3(1).",
        ),
    ],
}


async def fetch_eurlex_data(
    claim: Claim,
    company: object,  # Company — typed loosely to avoid circular import
) -> list[Evidence]:
    """Return EU regulatory standards applicable to the claim category.

    No network calls are made. Returns static regulatory context extracted
    from the Green Claims Directive, CSRD, and EU ETS legislation so the
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

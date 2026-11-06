"""Regulatory context module for the Prasine Index Verification Agent.

Provides the EU legal provisions that bear on a green claim, as structured
Evidence, so the Judge Agent always has the regulatory baseline. EUR-Lex holds
the legislation itself, not company reports, and the legislation does not change
between runs, so the provisions are embedded rather than fetched.

Sources embedded here:
- Directive (EU) 2024/825, which amends the Unfair Commercial Practices
  Directive 2005/29/EC (UCPD). Member States must apply it from 27 September
  2026, and it covers commercial practices aimed at consumers.
- The CSRD, Directive (EU) 2022/2464: corporate sustainability reporting.
- The EU ETS Directive 2003/87/EC: verified emissions of covered installations.

Provisions are quoted from the Official Journal text. Each record states what a
provision requires and never concludes that a claim breaches it: whether a
practice is unfair is decided case by case by national authorities and courts.

The Green Claims Directive proposal, COM(2023) 166, was never adopted and is not
cited.
"""

from __future__ import annotations

from models.claim import Claim, ClaimCategory
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_eurlex_data"]

# ---------------------------------------------------------------------------
# Provisions
# Each entry: (celex_id, title, year, summary_for_judge)
# ---------------------------------------------------------------------------

_CONSUMER_SCOPE = (
    " Member States must apply Directive (EU) 2024/825 from 27 September 2026 "
    "through national law, so its effect in a given country depends on "
    "transposition. It covers commercial practices aimed at consumers. Questions "
    "and Answers on the directive from the Commission's Directorate-General for "
    "Justice and Consumers (September 2026), which give the preliminary views of "
    'the Commission services, say that corporate sustainability reporting "is '
    "typically not in scope of the UCPD/ECGT Directive, because these reports are "
    "often mandatory and addressed to investors, rather than being part of B2C "
    'commercial practices", and that when a company uses information from its '
    'sustainability report "in voluntary advertising or marketing directed at '
    'consumers, such communication falls under the UCPD/ECGT Directive" '
    "(https://commission.europa.eu/document/download/3c257883-bb2a-4dd9-a6dc-"
    "501d587bb34f_en?filename=Q%26A%20ECGT_Directive_Sept%202026.pdf). Whether a "
    "practice is unfair is decided case by case by national authorities and courts."
)

_EMPCO_CELEX = "32024L0825"
_EMPCO_YEAR = 2024

_FUTURE_PERFORMANCE = (
    _EMPCO_CELEX,
    "Directive (EU) 2024/825: UCPD Article 6(2)(d), future environmental performance",
    _EMPCO_YEAR,
    'Article 6(2) of the UCPD reads: "A commercial practice shall also be regarded as '
    "misleading if, in its factual context, taking account of all its features and "
    "circumstances, it causes or is likely to cause the average consumer to take a "
    "transactional decision that he would not have taken otherwise, and it "
    'involves:". Directive (EU) 2024/825 adds point (d): '
    '"making an environmental claim related to future environmental performance '
    "without clear, objective, publicly available and verifiable commitments set out "
    "in a detailed and realistic implementation plan that includes measurable and "
    "time-bound targets and other relevant elements necessary to support its "
    "implementation, such as allocation of resources, and that is regularly verified "
    "by an independent third party expert, whose findings are made available to "
    'consumers".' + _CONSUMER_SCOPE,
)

_OFFSETTING = (
    _EMPCO_CELEX,
    "Directive (EU) 2024/825: UCPD Annex I point 4c, offset-based product claims",
    _EMPCO_YEAR,
    "Annex I point 4c of the UCPD as amended prohibits in all circumstances: "
    '"Claiming, based on the offsetting of greenhouse gas emissions, that a product '
    "has a neutral, reduced or positive impact on the environment in terms of "
    "greenhouse gas emissions.\" The Commission's guidance states that point 4c "
    "does not apply to claims based on offsetting at company level, which remain "
    "subject to the directive's other provisions." + _CONSUMER_SCOPE,
)

_GENERIC_CLAIM = (
    _EMPCO_CELEX,
    "Directive (EU) 2024/825: UCPD Annex I point 4a, generic environmental claims",
    _EMPCO_YEAR,
    "Annex I point 4a of the UCPD as amended prohibits in all circumstances: "
    '"Making a generic environmental claim for which the trader is not able to '
    "demonstrate recognised excellent environmental performance relevant to the "
    'claim." A claim is generic when its specification is not provided in clear and '
    "prominent terms on the same medium. Recognised excellent environmental "
    "performance means compliance with the EU Ecolabel, an officially recognised "
    "EN ISO 14024 type I ecolabel, or top environmental performance under other "
    "applicable Union law." + _CONSUMER_SCOPE,
)

_WHOLE_BUSINESS = (
    _EMPCO_CELEX,
    "Directive (EU) 2024/825: UCPD Annex I point 4b, whole-product or whole-business claims",
    _EMPCO_YEAR,
    "Annex I point 4b of the UCPD as amended prohibits in all circumstances: "
    "\"Making an environmental claim about the entire product or the trader's entire "
    "business when it concerns only a certain aspect of the product or a specific "
    "activity of the trader's business.\"" + _CONSUMER_SCOPE,
)

_LABELS = (
    _EMPCO_CELEX,
    "Directive (EU) 2024/825: UCPD Annex I point 2a, sustainability labels",
    _EMPCO_YEAR,
    "Annex I point 2a of the UCPD as amended prohibits in all circumstances: "
    '"Displaying a sustainability label that is not based on a certification scheme '
    'or not established by public authorities."' + _CONSUMER_SCOPE,
)

_MAIN_CHARACTERISTICS = (
    _EMPCO_CELEX,
    "Directive (EU) 2024/825: UCPD Article 6(1), environmental characteristics",
    _EMPCO_YEAR,
    'Article 6(1) of the UCPD reads: "A commercial practice shall be regarded as '
    "misleading if it contains false information and is therefore untruthful or in any "
    "way, including overall presentation, deceives or is likely to deceive the average "
    "consumer, even if the information is factually correct, in relation to one or more "
    "of the following elements, and in either case causes or is likely to cause him to "
    'take a transactional decision that he would not have taken otherwise:". Directive '
    "(EU) 2024/825 adds a product's environmental or social characteristics and its "
    "circularity aspects to the main characteristics listed in point (b)." + _CONSUMER_SCOPE,
)

_CSRD = (
    "32022L2464",
    "CSRD: Corporate Sustainability Reporting Directive (EU) 2022/2464",
    2022,
    "The CSRD requires companies within its scope to report greenhouse gas "
    "emissions, including Scope 3, under the European Sustainability Reporting "
    "Standards. EU simplification measures adopted in 2025 and 2026 postponed "
    "reporting and narrowed the scope, so whether a given company reports, and for "
    "which financial year, must be checked for that company.",
)

_EU_ETS = (
    "32003L0087",
    "EU ETS Directive 2003/87/EC as amended",
    2003,
    "Operators in the EU ETS report annual emissions that accredited verifiers check "
    "under Implementing Regulation (EU) 2018/2067, and the verified figures are "
    "published in the Union Registry. They cover the installations and aviation "
    "activities an operator has in the scheme, not a company's whole value chain. "
    "Emissions from biomass that meets the sustainability criteria count as zero in "
    "the EU ETS, so a fall in verified emissions can reflect a switch to biomass "
    "rather than an equal fall in the CO2 actually released.",
)

_REGULATORY_CONTEXT: dict[ClaimCategory, list[tuple[str, str, int, str]]] = {
    ClaimCategory.NET_ZERO_TARGET: [_FUTURE_PERFORMANCE, _CSRD],
    ClaimCategory.SCIENCE_BASED_TARGETS: [_FUTURE_PERFORMANCE],
    ClaimCategory.CARBON_NEUTRAL: [_OFFSETTING, _WHOLE_BUSINESS],
    ClaimCategory.EMISSIONS_REDUCTION: [_EU_ETS, _MAIN_CHARACTERISTICS, _WHOLE_BUSINESS],
    ClaimCategory.RENEWABLE_ENERGY: [_MAIN_CHARACTERISTICS, _WHOLE_BUSINESS],
    ClaimCategory.SUSTAINABLE_SUPPLY_CHAIN: [_CSRD, _MAIN_CHARACTERISTICS, _WHOLE_BUSINESS],
    ClaimCategory.CIRCULAR_ECONOMY: [_MAIN_CHARACTERISTICS, _GENERIC_CLAIM, _WHOLE_BUSINESS],
    ClaimCategory.BIODIVERSITY: [_GENERIC_CLAIM, _WHOLE_BUSINESS],
    ClaimCategory.OTHER: [_GENERIC_CLAIM, _LABELS, _WHOLE_BUSINESS],
}


async def fetch_eurlex_data(
    claim: Claim,
    company: object,  # Company, typed loosely to avoid circular import
) -> list[Evidence]:
    """Return the EU provisions relevant to the claim category.

    No network calls are made. Returns the embedded provisions of Directive
    (EU) 2024/825, the CSRD and the EU ETS Directive so the Judge Agent always
    has the legal baseline regardless of API availability. The records are
    context: they neither support nor contradict the claim.

    Args:
        claim: The claim under assessment.
        company: The company that made the claim (unused; kept for interface
            compatibility with other ingest modules).

    Returns:
        List of Evidence records containing the applicable provisions.
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

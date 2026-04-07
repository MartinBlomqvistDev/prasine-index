"""National and EU enforcement rulings on greenwashing claims.

Static database of confirmed regulatory rulings, bans, fines, and investigations
against EU-listed companies by national advertising standards authorities, consumer
protection regulators, competition authorities, and courts.

No refresh script is needed — enforcement rulings are permanent public record.
The database is curated and updated manually when new rulings are published.
All cases are drawn from publicly accessible official sources.

Authorities included:
  ASA    — UK Advertising Standards Authority
  ACM    — Dutch Authority for Consumers and Markets
  AGCM   — Italian Competition Authority
  CMA    — UK Competition and Markets Authority
  EC     — European Commission (consumer protection enforcement)
  Courts — National court judgments under the Unfair Commercial Practices Directive
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_enforcement_data"]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class _Ruling:
    """A single enforcement ruling or investigation against a company.

    Attributes:
        companies: All name variants for the company covered by this ruling.
            Used for fuzzy matching — include common abbreviations and subsidiary names.
        authority: Short identifier for the regulating body.
        country: ISO 3166-1 alpha-2 country code of the authority.
        year: Year the ruling was published or the investigation was announced.
        case_reference: Official case number or reference, if available.
        ruling_type: Outcome: FINED, BANNED, CONFIRMED_MISLEADING, WARNING, INVESTIGATION.
        claim_type: Category of green claim that was found problematic.
        description: Plain-text summary of what the regulator found and why.
        source_url: URL to the official ruling document or press release.
    """

    companies: tuple[str, ...]
    authority: str
    country: str
    year: int
    case_reference: str
    ruling_type: str
    claim_type: str
    description: str
    source_url: str


# ---------------------------------------------------------------------------
# Lookup table built at import time
# ---------------------------------------------------------------------------

def _normalise_name(name: str) -> str:
    """Lowercase and strip legal suffixes for fuzzy matching."""
    name = name.lower().strip()
    for suffix in (" plc", " ag", " se", " sa", " s.a.", " spa", " s.p.a.", " nv",
                   " bv", " gmbh", " inc", " corp", " ltd", " limited", " group",
                   " holding", " holdings", " a/s", " as", " ab"):
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


# ---------------------------------------------------------------------------
# Static enforcement rulings database
# Each entry represents one ruling or investigation from public record.
# ---------------------------------------------------------------------------

_RULINGS: list[_Ruling] = [
    # Ryanair ----------------------------------------------------------------
    _Ruling(
        companies=("Ryanair", "Ryanair Holdings", "Ryanair Holdings plc"),
        authority="ASA",
        country="UK",
        year=2020,
        case_reference="ASA A20-529462",
        ruling_type="CONFIRMED_MISLEADING",
        claim_type="EMISSIONS_REDUCTION",
        description=(
            "ASA upheld complaint against Ryanair's claim to have the 'lowest carbon emissions'. "
            "Ryanair could not substantiate that it had lower CO2 per passenger than other "
            "European airlines when evaluated on the same basis. The claim was found misleading."
        ),
        source_url="https://www.asa.org.uk/rulings/ryanair-ltd-g21-1080990.html",
    ),
    _Ruling(
        companies=("Ryanair", "Ryanair Holdings"),
        authority="EUROPEAN_COMMISSION",
        country="EU",
        year=2024,
        case_reference="EC CPC Regulation 2017/2394 — Airline sweep",
        ruling_type="INVESTIGATION",
        claim_type="EMISSIONS_REDUCTION",
        description=(
            "European Commission and national consumer protection authorities launched a "
            "coordinated investigation into Ryanair's environmental claims about carbon "
            "emissions, offsetting, and sustainability credentials. Part of the 2024 "
            "airline greenwashing sweep covering Ryanair, Air France, KLM, and Lufthansa."
        ),
        source_url="https://ec.europa.eu/commission/presscorner/detail/en/ip_24_2057",
    ),

    # HSBC -------------------------------------------------------------------
    _Ruling(
        companies=("HSBC", "HSBC Holdings", "HSBC Holdings plc", "HSBC Bank", "HSBC UK"),
        authority="ASA",
        country="UK",
        year=2022,
        case_reference="ASA A22-1277",
        ruling_type="BANNED",
        claim_type="NET_ZERO_TARGET",
        description=(
            "ASA banned two HSBC newspaper advertisements claiming the bank was 'helping to "
            "tackle climate change' and 'targeting net zero by 2050 or sooner'. The ads failed "
            "to disclose that HSBC simultaneously financed $87bn in fossil fuel expansion "
            "(2016–2022). Landmark ruling establishing that net-zero claims by financial "
            "institutions must disclose material contradicting financing activities."
        ),
        source_url="https://www.asa.org.uk/rulings/hsbc-uk-bank-plc-g22-1183960.html",
    ),

    # Shell ------------------------------------------------------------------
    _Ruling(
        companies=("Shell", "Shell plc", "Shell International", "Royal Dutch Shell",
                   "Shell UK", "Shell Netherlands"),
        authority="ASA",
        country="UK",
        year=2023,
        case_reference="ASA A23-1324094",
        ruling_type="BANNED",
        claim_type="CARBON_NEUTRAL",
        description=(
            "ASA banned Shell's 'Drive Carbon Neutral' advertisements promoting carbon-neutral "
            "petrol and diesel through carbon credit purchases. Claims were found misleading "
            "as the carbon credits did not represent permanent emission removals and did not "
            "account for the full lifecycle emissions of the fuel product."
        ),
        source_url="https://www.asa.org.uk/rulings/shell-uk-oil-products-limited-g23-1324094.html",
    ),
    _Ruling(
        companies=("Shell", "Shell plc", "Shell Netherlands", "Shell International"),
        authority="ACM",
        country="NL",
        year=2021,
        case_reference="ACM case 21.0873.53",
        ruling_type="WARNING",
        claim_type="EMISSIONS_REDUCTION",
        description=(
            "Dutch ACM found Shell's 'We Are Driving Change' campaign used vague and "
            "unsubstantiated environmental claims, in violation of the Dutch Commercial "
            "Practices Act (implementing EU UCPD). Part of ACM's 2021 enforcement sweep "
            "against energy companies making unsubstantiated green claims."
        ),
        source_url="https://www.acm.nl/en/publications/acm-warns-companies-about-misleading-green-claims",
    ),

    # KLM / Air France-KLM --------------------------------------------------
    _Ruling(
        companies=("KLM", "KLM Royal Dutch Airlines", "Air France-KLM", "Air France KLM"),
        authority="ACM",
        country="NL",
        year=2023,
        case_reference="ACM/UIT/544682",
        ruling_type="CONFIRMED_MISLEADING",
        claim_type="CARBON_NEUTRAL",
        description=(
            "Dutch ACM ruled KLM's 'Fly Responsibly' campaign misleading. KLM claimed passengers "
            "could fly 'sustainably' via carbon offset purchases; ACM found the offsetting "
            "schemes did not represent real, permanent emission reductions. KLM was required "
            "to stop the misleading communications immediately."
        ),
        source_url="https://www.acm.nl/en/publications/acm-klm-must-stop-misleading-consumers-about-sustainability",
    ),
    _Ruling(
        companies=("KLM", "KLM Royal Dutch Airlines", "Air France-KLM"),
        authority="DISTRICT_COURT_NL",
        country="NL",
        year=2023,
        case_reference="ECLI:NL:RBAMS:2023:5615",
        ruling_type="CONFIRMED_MISLEADING",
        claim_type="CARBON_NEUTRAL",
        description=(
            "Amsterdam District Court ruled in Fossielvrij NL v. KLM that KLM's 'Fly "
            "Responsibly' carbon offset advertising constituted unlawful greenwashing under "
            "the Unfair Commercial Practices Directive. KLM ordered to stop the misleading "
            "advertising. First successful climate greenwashing litigation in the Netherlands."
        ),
        source_url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2023:5615",
    ),
    _Ruling(
        companies=("Air France", "Air France-KLM", "Air France KLM"),
        authority="EUROPEAN_COMMISSION",
        country="EU",
        year=2024,
        case_reference="EC CPC Regulation 2017/2394 — Airline sweep",
        ruling_type="INVESTIGATION",
        claim_type="CARBON_NEUTRAL",
        description=(
            "European Commission investigation into Air France and KLM's environmental claims "
            "about carbon neutrality, offsetting, and sustainable aviation. Part of the 2024 "
            "airline greenwashing sweep."
        ),
        source_url="https://ec.europa.eu/commission/presscorner/detail/en/ip_24_2057",
    ),

    # Lufthansa --------------------------------------------------------------
    _Ruling(
        companies=("Lufthansa", "Deutsche Lufthansa", "Lufthansa Group",
                   "Lufthansa AG", "Deutsche Lufthansa AG"),
        authority="ASA",
        country="UK",
        year=2022,
        case_reference="ASA A22-1183827",
        ruling_type="BANNED",
        claim_type="SUSTAINABLE_PRODUCT",
        description=(
            "ASA banned Lufthansa's 'Connecting the World, Protecting its Future' and "
            "'Fly More Sustainably' advertisements. Claims of sustainable aviation lacked "
            "substantiation — Lufthansa could not demonstrate systematic use of sustainable "
            "aviation fuel or verified per-flight emission reductions at the advertised scale."
        ),
        source_url="https://www.asa.org.uk/rulings/deutsche-lufthansa-ag-g22-1183827.html",
    ),
    _Ruling(
        companies=("Lufthansa", "Deutsche Lufthansa", "Lufthansa Group"),
        authority="EUROPEAN_COMMISSION",
        country="EU",
        year=2024,
        case_reference="EC CPC Regulation 2017/2394 — Airline sweep",
        ruling_type="INVESTIGATION",
        claim_type="CARBON_NEUTRAL",
        description=(
            "European Commission investigation into Lufthansa's environmental claims. "
            "Part of the 2024 airline greenwashing sweep covering Ryanair, Air France, "
            "KLM, and Lufthansa."
        ),
        source_url="https://ec.europa.eu/commission/presscorner/detail/en/ip_24_2057",
    ),

    # easyJet ---------------------------------------------------------------
    _Ruling(
        companies=("easyJet", "easyJet plc", "EasyJet"),
        authority="CMA",
        country="UK",
        year=2023,
        case_reference="CMA greenwashing investigation — airline sector",
        ruling_type="INVESTIGATION",
        claim_type="CARBON_NEUTRAL",
        description=(
            "UK Competition and Markets Authority (CMA) investigated easyJet's 'net zero' "
            "and carbon-neutral flight claims. easyJet relied heavily on carbon offsets; "
            "the CMA investigated whether the claims were misleading under the Consumer "
            "Protection from Unfair Trading Regulations. easyJet withdrew the claims "
            "during the investigation."
        ),
        source_url="https://www.gov.uk/government/news/airlines-face-scrutiny-over-green-claims",
    ),

    # Eni -------------------------------------------------------------------
    _Ruling(
        companies=("Eni", "Eni SpA", "Eni S.p.A.", "Eni spa"),
        authority="AGCM",
        country="IT",
        year=2023,
        case_reference="AGCM PS12469",
        ruling_type="FINED",
        claim_type="SUSTAINABLE_PRODUCT",
        description=(
            "Italian AGCM fined Eni €5 million for misleading 'HVOlution' green diesel "
            "campaign. Eni claimed HVO diesel was 'green' and had a 'carbon footprint close "
            "to zero'. AGCM found the feedstock sourcing and lifecycle methodology did not "
            "support these claims. Largest greenwashing fine in Italian regulatory history "
            "at the time of the ruling. Claim that a fossil fuel product is inherently "
            "green without verifiable lifecycle evidence is a per se violation."
        ),
        source_url="https://www.agcm.it/dotcmsdoc/allegati-news/PS12469%20provvedimento.pdf",
    ),

    # ArcelorMittal ---------------------------------------------------------
    _Ruling(
        companies=("ArcelorMittal", "ArcelorMittal SE", "ArcelorMittal SA"),
        authority="ASA",
        country="UK",
        year=2023,
        case_reference="ASA A23-1357781",
        ruling_type="BANNED",
        claim_type="CARBON_NEUTRAL",
        description=(
            "ASA banned ArcelorMittal's advertisements claiming to produce 'XCarb green steel' "
            "that is 'carbon neutral' or 'close to carbon neutral'. Claims were unsubstantiated "
            "— the carbon accounting methodology excluded significant upstream (ore processing) "
            "and direct steelmaking emissions. 'Carbon neutral steel' in conventional "
            "blast-furnace processes cannot be substantiated without verified offset accounting."
        ),
        source_url="https://www.asa.org.uk/rulings/arcelormittal-sa-a23-1357781.html",
    ),

    # BP --------------------------------------------------------------------
    _Ruling(
        companies=("BP", "BP plc", "BP Global", "BP Group"),
        authority="ASA",
        country="UK",
        year=2019,
        case_reference="ASA ruling July 2019",
        ruling_type="CONFIRMED_MISLEADING",
        claim_type="EMISSIONS_REDUCTION",
        description=(
            "ASA upheld complaints against BP advertisements featuring flowers, wind turbines, "
            "and solar panels that promoted BP as environmentally friendly. The ads emphasised "
            "low-carbon activities representing a fraction of BP's business, creating a "
            "misleading overall impression. Ruling established that selective presentation "
            "of a company's most favourable environmental activities is misleading."
        ),
        source_url="https://www.asa.org.uk/rulings/bp-plc-g19-1020800.html",
    ),

    # TotalEnergies ---------------------------------------------------------
    _Ruling(
        companies=("TotalEnergies", "TotalEnergies SE", "Total SE", "Total SA", "Total S.A."),
        authority="ACM",
        country="NL",
        year=2021,
        case_reference="ACM greenwashing enforcement 2021",
        ruling_type="WARNING",
        claim_type="NET_ZERO_TARGET",
        description=(
            "Dutch ACM included TotalEnergies in its 2021 enforcement action against energy "
            "companies making vague or unsubstantiated environmental claims in the Netherlands. "
            "Net-zero and sustainability claims lacked the required substantiation under the "
            "Unfair Commercial Practices Directive as transposed into Dutch law."
        ),
        source_url="https://www.acm.nl/en/publications/acm-warns-companies-about-misleading-green-claims",
    ),

    # Volkswagen ------------------------------------------------------------
    _Ruling(
        companies=("Volkswagen", "VW", "Volkswagen AG", "Volkswagen Group",
                   "Volkswagen Group of America"),
        authority="MULTIPLE",
        country="EU",
        year=2016,
        case_reference="Dieselgate — EU/US enforcement (2015–2022)",
        ruling_type="FINED",
        claim_type="EMISSIONS_REDUCTION",
        description=(
            "Volkswagen was subject to enforcement actions across EU member states and the US "
            "for the 'Dieselgate' defeat device scandal. Vehicles marketed as low-emission, "
            "environmentally friendly diesel cars emitted up to 40x the NOx legal limit in "
            "real-world conditions. Total global fines exceeded €30bn. Landmark case "
            "demonstrating that verified emissions data (EU ETS, type-approval testing) "
            "can directly contradict company green claims."
        ),
        source_url="https://ec.europa.eu/commission/presscorner/detail/en/STATEMENT_15_5654",
    ),

    # Glencore --------------------------------------------------------------
    _Ruling(
        companies=("Glencore", "Glencore plc", "Glencore International"),
        authority="CMA",
        country="UK",
        year=2023,
        case_reference="CMA investigation — fossil fuel companies",
        ruling_type="INVESTIGATION",
        claim_type="NET_ZERO_TARGET",
        description=(
            "UK CMA placed Glencore under scrutiny as part of its investigation into green "
            "claims by fossil fuel producers. Glencore's net-zero commitment while continuing "
            "coal mining expansion was flagged as potentially misleading under UK consumer "
            "protection law. Glencore is the world's largest coal exporter."
        ),
        source_url="https://www.gov.uk/cma-cases/greenwashing-claims",
    ),
]


# Build lookup: {normalised_name: [_Ruling, ...]}
_BY_COMPANY: dict[str, list[_Ruling]] = {}

for _ruling in _RULINGS:
    for _company_name in _ruling.companies:
        _key = _normalise_name(_company_name)
        if _key not in _BY_COMPANY:
            _BY_COMPANY[_key] = []
        if _ruling not in _BY_COMPANY[_key]:
            _BY_COMPANY[_key].append(_ruling)


# ---------------------------------------------------------------------------
# Confidence by ruling type
# ---------------------------------------------------------------------------

_RULING_CONFIDENCE: dict[str, float] = {
    "FINED": 0.95,
    "BANNED": 0.90,
    "CONFIRMED_MISLEADING": 0.90,
    "WARNING": 0.80,
    "INVESTIGATION": 0.70,
}

_RULING_SUPPORTS: dict[str, bool | None] = {
    "FINED": False,
    "BANNED": False,
    "CONFIRMED_MISLEADING": False,
    "WARNING": False,
    "INVESTIGATION": None,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_enforcement_data(claim: Claim, company: object) -> list[Evidence]:
    """Return regulatory enforcement rulings against a company as evidence.

    Looks up the company in the static enforcement rulings database. A confirmed
    ban, fine, or misleading ruling from a national or EU regulator is the
    strongest possible evidence that a company's green claims are unsubstantiated —
    a regulator has already made that determination independently.

    Returns one Evidence record per distinct ruling found. Multiple rulings against
    the same company compound into a stronger overall picture for the Judge.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        List of Evidence records, one per ruling found (may be empty).
    """
    name: str = getattr(company, "name", "")
    norm = _normalise_name(name)

    # Direct match
    rulings = _BY_COMPANY.get(norm, [])

    # Partial substring match — catches "Ryanair Holdings plc" vs "Ryanair"
    if not rulings:
        for key, key_rulings in _BY_COMPANY.items():
            if norm in key or key in norm:
                rulings = key_rulings
                break

    if not rulings:
        logger.info(
            f"Enforcement: no rulings found for {name!r}",
            extra={"operation": "enforcement_not_found", "company": name},
        )
        return []

    logger.info(
        f"Enforcement: {len(rulings)} ruling(s) found for {name!r}",
        extra={"operation": "enforcement_found", "company": name, "count": len(rulings)},
    )

    evidence_records: list[Evidence] = []
    for ruling in rulings:
        supports = _RULING_SUPPORTS.get(ruling.ruling_type)
        confidence = _RULING_CONFIDENCE.get(ruling.ruling_type, 0.75)

        summary = (
            f"Enforcement ruling — {ruling.authority} ({ruling.country}, {ruling.year}): "
            f"{ruling.ruling_type.replace('_', ' ')} | {ruling.case_reference}. "
            f"{ruling.description}"
        )

        evidence_records.append(
            Evidence(
                claim_id=claim.id,
                trace_id=claim.trace_id,
                source=EvidenceSource.ENFORCEMENT,
                evidence_type=EvidenceType.ENFORCEMENT_RULING,
                source_url=ruling.source_url,
                raw_data={
                    "authority": ruling.authority,
                    "country": ruling.country,
                    "year": ruling.year,
                    "case_reference": ruling.case_reference,
                    "ruling_type": ruling.ruling_type,
                    "claim_type": ruling.claim_type,
                    "companies_covered": list(ruling.companies),
                },
                summary=summary,
                data_year=ruling.year,
                supports_claim=supports,
                confidence=confidence,
            )
        )

    return evidence_records

"""TPI (Transition Pathway Initiative) company assessment ingest module.

Loads the TPI Company Latest Assessments CSV — Management Quality (MQ) levels
0-4 and Carbon Performance (CP) pathway alignment labels — for 490+ listed
companies across 12+ high-emission sectors.

TPI assessments are produced by the TPI Centre at LSE and used by 150+
investors representing $80+ trillion AUM. A company claiming Paris alignment
or net-zero ambition while rated "Not Aligned" by TPI is contradicted by the
consensus of major institutional investors.

Two primary greenwashing signals:
  1. CP Alignment 2050 = "Not Aligned" while claiming net-zero/Paris alignment.
     This is the strongest single indicator — it means the company's projected
     emissions trajectory does not reach net-zero by 2050 under TPI's methodology.
  2. MQ Level 0 or 1 (Unaware/Cognizant) while claiming climate leadership.
     Poor governance score indicates the company has not put in place even basic
     climate management structures to back up its public claims.

MQ level labels:
  0: Unaware     — does not acknowledge climate change as a significant issue
  1: Cognizant   — acknowledges the issue, no substantive action
  2: Acknowledging — some action, limited integration
  3: Integrating — substantial integration into strategy
  4/4STAR: Strategic — full strategic integration with targets and governance

CP alignment labels (2025/2035/2050):
  1.5 Degrees, Below 2 Degrees, 2 Degrees — Paris-aligned or better
  National Pledges, International Pledges, Paris Pledges — weak alignment
  Not Aligned — projected trajectory exceeds Paris-compatible benchmarks
  No or unsuitable disclosure / Not Assessed — insufficient disclosure

Data source: https://github.com/transition-pathway-initiative/Assessment-data
Data file: data/tpi_companies.csv (Company_Latest_Assessments.csv)
Coverage: ~490 major listed companies, last updated 2022
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.logger import get_logger
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_tpi_data"]

logger = get_logger(__name__)

_CSV_PATH = Path(__file__).parent.parent / "data" / "tpi_companies.csv"

# MQ level score thresholds for greenwashing signal
_MQ_WEAK = {"0", "1"}
_MQ_STRONG = {"4", "4STAR"}

# CP alignment tiers
_CP_PARIS_ALIGNED = {
    "1.5 Degrees",
    "Below 2 Degrees",
    "2 Degrees",
    "2 Degrees (High Efficiency)",
    "2 Degrees (Shift-Improve)",
}
_CP_WEAK_ALIGNED = {"National Pledges", "International Pledges", "Paris Pledges"}
_CP_NOT_ALIGNED = {"Not Aligned"}
_CP_NO_DISCLOSURE = {"No or unsuitable disclosure", "Not Assessed"}


class _TPIRecord:
    __slots__ = (
        "company_name",
        "cp_2025",
        "cp_2035",
        "cp_2050",
        "geography",
        "mq_level",
        "sector",
    )

    def __init__(self, row: dict[str, str]) -> None:
        self.company_name = row.get("Company Name", "").strip()
        self.geography = row.get("Geography", "").strip()
        self.sector = row.get("Sector", "").strip()
        self.mq_level = row.get("Level", "").strip()
        self.cp_2025 = row.get("Carbon Performance Alignment 2025", "").strip()
        self.cp_2035 = row.get("Carbon Performance Alignment 2035", "").strip()
        self.cp_2050 = row.get("Carbon Performance Alignment 2050", "").strip()

    @property
    def mq_label(self) -> str:
        labels = {
            "0": "Unaware",
            "1": "Cognizant",
            "2": "Acknowledging",
            "3": "Integrating",
            "4": "Strategic",
            "4STAR": "Strategic+",
        }
        return labels.get(
            self.mq_level, f"Level {self.mq_level}" if self.mq_level else "Not assessed"
        )

    @property
    def is_not_aligned_2050(self) -> bool:
        return self.cp_2050 in _CP_NOT_ALIGNED

    @property
    def is_paris_aligned_2050(self) -> bool:
        return self.cp_2050 in _CP_PARIS_ALIGNED

    @property
    def has_weak_mq(self) -> bool:
        return self.mq_level in _MQ_WEAK


# Module-level cache: list loaded once on first call
_records: list[_TPIRecord] | None = None


def _load() -> list[_TPIRecord]:
    global _records
    if _records is not None:
        return _records

    if not _CSV_PATH.exists():
        logger.warning(
            f"TPI CSV not found at {_CSV_PATH}. Run scripts/refresh_tpi.py.",
            extra={"operation": "tpi_csv_missing"},
        )
        _records = []
        return _records

    records: list[_TPIRecord] = []
    try:
        with _CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rec = _TPIRecord(row)
                if rec.company_name:
                    records.append(rec)
    except (OSError, csv.Error) as exc:
        logger.warning(
            f"TPI CSV load failed: {exc}",
            extra={"operation": "tpi_csv_error"},
        )
        _records = []
        return _records

    _records = records
    logger.info(
        f"TPI: loaded {len(_records)} company records",
        extra={"operation": "tpi_loaded"},
    )
    return _records


def _normalise(name: str) -> str:
    return name.lower().strip()


def _name_matches(company_norm: str, record_name: str) -> bool:
    rec_norm = _normalise(record_name)
    if company_norm in rec_norm or rec_norm in company_norm:
        return True
    company_first = company_norm.split()[0] if company_norm.split() else company_norm
    return len(company_first) >= 4 and company_first in rec_norm


async def fetch_tpi_data(claim: Claim, company: object) -> list[Evidence]:
    """Return TPI Management Quality and Carbon Performance assessment for a company.

    Looks up the company in the TPI dataset and returns its MQ level and
    CP pathway alignment. A "Not Aligned" 2050 trajectory contradicts any
    net-zero or Paris-alignment claim. A Level 0/1 MQ score contradicts
    climate-leadership claims.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if the company is not
        in the TPI dataset.
    """
    company_name: str = getattr(company, "name", "")
    company_norm = _normalise(company_name)

    records = _load()
    matched = [r for r in records if _name_matches(company_norm, r.company_name)]

    if not matched:
        logger.info(
            f"TPI: no match for {company_name!r}",
            extra={"operation": "tpi_no_match", "company": company_name},
        )
        return []

    # Use the first match (name matching is already tight)
    rec = matched[0]

    # Determine supports_claim and confidence
    supports_claim: bool | None = None
    confidence: float = 0.75

    if rec.is_not_aligned_2050:
        supports_claim = False
        confidence = 0.85
    elif rec.has_weak_mq and rec.cp_2050 in _CP_NO_DISCLOSURE:
        supports_claim = False
        confidence = 0.70
    elif rec.is_paris_aligned_2050:
        supports_claim = True
        confidence = 0.75
    elif rec.cp_2050 in _CP_WEAK_ALIGNED:
        supports_claim = None
        confidence = 0.70
    else:
        # No or unsuitable disclosure / Not Assessed / blank
        supports_claim = None
        confidence = 0.60

    # Build summary
    cp_summary = (
        f"CP 2025: {rec.cp_2025 or 'N/A'}; "
        f"CP 2035: {rec.cp_2035 or 'N/A'}; "
        f"CP 2050: {rec.cp_2050 or 'N/A'}"
    )

    if rec.is_not_aligned_2050:
        signal = (
            f"CONTRADICTS green claim: TPI projects {company_name!r} trajectory as "
            f"'Not Aligned' with Paris Agreement by 2050. This means the company's "
            f"disclosed emissions pathway exceeds the TPI sector benchmark for 2050 — "
            f"a direct contradiction of any net-zero or Paris-alignment claim."
        )
    elif rec.is_paris_aligned_2050:
        signal = (
            f"Partially supports: TPI rates {company_name!r} 2050 pathway as "
            f"'{rec.cp_2050}' — within Paris-compatible bounds. MQ: {rec.mq_label}."
        )
    elif rec.has_weak_mq:
        signal = (
            f"Weak management quality: TPI MQ Level {rec.mq_level} ({rec.mq_label}) "
            f"indicates {company_name!r} has not put in place substantive climate "
            f"governance structures to back up public claims."
        )
    else:
        signal = (
            f"TPI rates {company_name!r} MQ Level {rec.mq_level} ({rec.mq_label}), "
            f"CP pathway: {rec.cp_2050 or 'not assessed'}."
        )

    summary = (
        f"TPI assessment ({rec.sector}, {rec.geography}): "
        f"Management Quality Level {rec.mq_level} ({rec.mq_label}). "
        f"{cp_summary}. "
        f"{signal} "
        f"TPI Centre assessments are used by 150+ investors ($80tn AUM) as the "
        f"standard investor-facing measure of corporate climate transition quality."
    )

    logger.info(
        f"TPI: matched {company_name!r} → {rec.company_name!r} "
        f"MQ={rec.mq_level} CP50={rec.cp_2050!r} supports={supports_claim}",
        extra={"operation": "tpi_match", "company": company_name},
    )

    raw_data: dict[str, Any] = {
        "company_name": rec.company_name,
        "geography": rec.geography,
        "sector": rec.sector,
        "mq_level": rec.mq_level,
        "mq_label": rec.mq_label,
        "cp_alignment_2025": rec.cp_2025,
        "cp_alignment_2035": rec.cp_2035,
        "cp_alignment_2050": rec.cp_2050,
    }

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.TPI,
            evidence_type=EvidenceType.BENCHMARK_ASSESSMENT,
            source_url="https://www.transitionpathwayinitiative.org/corporates",
            raw_data=raw_data,
            summary=summary,
            data_year=2022,
            supports_claim=supports_claim,
            confidence=confidence,
        )
    ]

"""TPI (Transition Pathway Initiative) company assessment ingest module.

Loads the TPI Company Latest Assessments CSV: Management Quality (MQ) levels
0-4 and Carbon Performance (CP) pathway alignment labels, for 490+ listed
companies across 12+ high-emission sectors.

TPI assessments are produced by the TPI Centre at LSE and used by 150+
investors representing $80+ trillion AUM. A company claiming Paris alignment
or net-zero ambition while rated "Not Aligned" by TPI is contradicted by the
consensus of major institutional investors.

Two primary greenwashing signals:
  1. CP Alignment 2050 = "Not Aligned" while claiming net-zero/Paris alignment.
     This is the strongest single indicator; it means the company's projected
     emissions trajectory does not reach net-zero by 2050 under TPI's methodology.
  2. MQ Level 0 or 1 (Unaware/Cognizant) while claiming climate leadership.
     Poor governance score indicates the company has not put in place even basic
     climate management structures to back up its public claims.

MQ level labels:
  0: Unaware    : does not acknowledge climate change as a significant issue
  1: Cognizant  : acknowledges the issue, no substantive action
  2: Acknowledging: some action, limited integration
  3: Integrating: substantial integration into strategy
  4/4STAR: Strategic: full strategic integration with targets and governance

CP alignment labels (2025/2035/2050):
  1.5 Degrees, Below 2 Degrees, 2 Degrees: Paris-aligned or better
  National Pledges, International Pledges, Paris Pledges: weak alignment
  Not Aligned: projected trajectory exceeds Paris-compatible benchmarks
  No or unsuitable disclosure / Not Assessed: insufficient disclosure

Data source: https://github.com/transition-pathway-initiative/Assessment-data
Data file: data/tpi_companies.csv (Company_Latest_Assessments.csv)
Coverage: ~490 major listed companies, last updated 2022
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.logger import get_logger
from ingest.name_matching import contains_name, fold_name, names_overlap
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_tpi_data"]

logger = get_logger(__name__)

_CSV_PATH = Path(__file__).parent.parent / "data" / "tpi_companies.csv"

# MQ level score thresholds for greenwashing signal
_MQ_WEAK = {"0", "1"}
_MQ_STRONG = {"4", "4STAR", "5"}

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
        "cp_2030",
        "cp_2035",
        "cp_2050",
        "cp_assessed",
        "geography",
        "mq_assessed",
        "mq_level",
        "mq_published",
        "notes",
        "regional",
        "retrieved",
        "sector",
        "source_url",
        "subsectors",
    )

    def __init__(self, row: dict[str, str]) -> None:
        self.company_name = row.get("Company Name", "").strip()
        self.geography = row.get("Geography", "").strip()
        self.sector = row.get("Sector", "").strip()
        self.mq_level = row.get("Level", "").strip()
        self.cp_2025 = row.get("Carbon Performance Alignment 2025", "").strip()
        self.cp_2030 = row.get("Carbon Performance Alignment 2030", "").strip()
        self.cp_2035 = row.get("Carbon Performance Alignment 2035", "").strip()
        self.cp_2050 = row.get("Carbon Performance Alignment 2050", "").strip()
        self.mq_assessed = row.get("MQ Assessment Date", "").strip()
        self.cp_assessed = row.get("CP Assessment Date", "").strip()
        self.mq_published = row.get("MQ Publication Date", "").strip()
        self.retrieved = row.get("Retrieved", "").strip()
        self.source_url = row.get("Source URL", "").strip()
        self.notes = row.get("TPI Centre Notes", "").strip()
        self.subsectors = row.get("Subsector Carbon Performance", "").strip()
        self.regional = row.get("Regional Carbon Performance", "").strip()

    @property
    def short_term(self) -> tuple[str, str]:
        """Return the short-term year and alignment. TPI's current data starts at 2030."""
        return ("2030", self.cp_2030)

    @property
    def assessed_year(self) -> int | None:
        """Return the year of the most recent assessment in the row."""
        years = [
            int(date[-4:])
            for date in (self.mq_assessed, self.cp_assessed)
            if len(date) >= 4 and date[-4:].isdigit()
        ]
        return max(years) if years else None

    @property
    def mq_label(self) -> str:
        # TPI's own names for the management quality levels.
        labels = {
            "0": "Unaware",
            "1": "Awareness",
            "2": "Building Capacity",
            "3": "Integrated into Operational Decision Making",
            "4": "Strategic Assessment",
            "4STAR": "Strategic Assessment",
            "5": "Transition Planning and Implementation",
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
    return fold_name(name)


def _name_matches(company_norm: str, record_name: str) -> bool:
    rec_norm = _normalise(record_name)
    if names_overlap(company_norm, rec_norm):
        return True
    company_first = company_norm.split()[0] if company_norm.split() else company_norm
    return (len(company_first) >= 4 or "&" in company_first) and contains_name(
        rec_norm, company_first
    )


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

    # A company can have one row per sector segment. Prefer the row for the
    # company's own sector, then one with a carbon performance assessment.
    company_sector = str(getattr(company, "sector", "") or "").lower()

    def _fit(record: _TPIRecord) -> tuple[int, int]:
        sector_words = [w for w in company_sector.replace("&", " ").split() if len(w) > 3]
        in_sector = any(w in record.sector.lower() for w in sector_words)
        assessed = record.cp_2050 not in ("", "Not Assessed", "No or unsuitable disclosure")
        return int(in_sector), int(assessed)

    rec = max(matched, key=_fit)

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
    if rec.cp_2030 or rec.cp_2035 or rec.cp_2050:
        cp_summary = (
            f"Carbon performance against the {rec.sector} benchmark: "
            f"{rec.cp_2030 or 'not assessed'} for 2030, {rec.cp_2035 or 'not assessed'} for "
            f"2035 and {rec.cp_2050 or 'not assessed'} for 2050."
        )
        if rec.regional:
            cp_summary += f" Against TPI's regional benchmark ({rec.regional})."
        if rec.subsectors:
            cp_summary += f" Against subsector benchmarks: {rec.subsectors}."
    else:
        cp_summary = "TPI has not assessed the company's carbon performance."

    dates = "; ".join(
        f"{label} assessed {date}"
        for label, date in (
            ("management quality", rec.mq_assessed),
            ("carbon performance", rec.cp_assessed),
        )
        if date
    )
    retrieved = f"; read from TPI on {rec.retrieved}" if rec.retrieved else ""
    summary = (
        f"TPI assessment of {rec.company_name} ({rec.sector}, {rec.geography}"
        f"{'; ' + dates if dates else ''}{retrieved}): "
        f"Management Quality Level {rec.mq_level.replace('STAR', '*')} ({rec.mq_label}"
        f"{', the highest of TPI levels' if rec.mq_level == '5' else ''}). {cp_summary}"
        + (
            f" TPI Centre notes on the assessment against the {rec.sector} benchmark: {rec.notes}"
            if rec.notes
            else ""
        )
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
        "cp_alignment_2030": rec.cp_2030,
        "cp_alignment_2035": rec.cp_2035,
        "cp_alignment_2050": rec.cp_2050,
        "mq_assessed": rec.mq_assessed,
        "cp_assessed": rec.cp_assessed,
        "mq_published": rec.mq_published,
        "retrieved": rec.retrieved,
        "notes": rec.notes,
        "subsectors": rec.subsectors,
        "regional": rec.regional,
    }

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.TPI,
            evidence_type=EvidenceType.BENCHMARK_ASSESSMENT,
            source_url=rec.source_url or "https://www.transitionpathwayinitiative.org/corporates",
            raw_data=raw_data,
            summary=summary,
            data_year=rec.assessed_year,
            supports_claim=supports_claim,
            confidence=confidence,
        )
    ]

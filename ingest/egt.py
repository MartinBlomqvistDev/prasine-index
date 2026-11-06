"""Europe Gas Tracker (EGT) ingest module for the Prasine Index.

Loads the GEM Europe Gas Tracker Excel file: facility-level data on gas
pipelines, LNG import/export terminals, and oil & gas plants in Europe.

The key greenwashing signal: a European energy company that claims to be
transitioning away from fossil gas or pursuing a net-zero strategy while
owning gas pipelines or LNG terminals in active development (proposed or
under construction) is directly contradicted by its infrastructure pipeline.

Coverage (three sheets used):
  Gas Pipelines: proposed, under-construction, and operating gas pipelines
    across Europe. Owner and Parent fields identify corporate operators.
  LNG Terminals: liquefied natural gas import/export terminals. A company
    claiming gas phase-out while building new LNG import capacity contradicts
    that claim; LNG infrastructure has a 40-50 year economic lifetime.
  Oil & Gas Plants: gas-fired power plants in Europe. Expanding gas generation
    capacity contradicts renewable energy transition claims.

Status values:
  Gas Pipelines: operating, proposed, construction, shelved, cancelled, retired
  LNG Terminals: operating, proposed, construction, shelved, cancelled, retired
  O&G Plants:    operating, announced, pre-construction, construction,
                 shelved, cancelled, retired, mothballed

Greenwashing signal logic:
  Expanding (proposed/announced/pre-construction/construction):
    → supports_claim=False, confidence=0.85
  Operating only (no expansion):
    → supports_claim=None, confidence=0.60
  Exiting (shelved/cancelled only, no expansion):
    → supports_claim=True, confidence=0.55

Data file: data/Europe-Gas-Tracker-2026-03-02.xlsx
Refresh: scripts/refresh_egt.py (manual: form + reCAPTCHA required)
Coverage: European gas infrastructure, March 2026 release
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from core.logger import get_logger
from ingest.name_matching import contains_name, names_overlap
from models.claim import Claim
from models.evidence import Evidence, EvidenceSource, EvidenceType

__all__ = ["fetch_egt_data", "stalled_lng"]

logger = get_logger(__name__)

_XLSX_PATH = Path(__file__).parent.parent / "data" / "Europe-Gas-Tracker-2026-03-02.xlsx"

_EXPANDING_STATUSES = {"proposed", "announced", "pre-construction", "construction"}
_OPERATING_STATUSES = {"operating"}
_EXITING_STATUSES = {
    "shelved",
    "cancelled",
    "retired",
    "mothballed",
    "shelved - inferred 2 y",
    "cancelled - inferred 4 y",
}


# A project still at the proposal stage this many years after it was proposed is not
# counted as new supply: it is listed, with its proposal year, as long stalled.
STALLED_YEARS = 10


def _data_year() -> int:
    """Return the year of the tracker file, from its name, or this year."""
    found = re.search(r"(20\d\d)-\d\d-\d\d", _XLSX_PATH.name)
    return int(found.group(1)) if found else date.today().year


class _EGTAsset:
    __slots__ = (
        "asset_type",
        "capacity",
        "country",
        "detail",
        "mtpa",
        "name",
        "owner_raw",
        "parent_raw",
        "proposal_year",
        "status",
    )

    def __init__(
        self,
        name: str,
        country: str,
        status: str,
        owner_raw: str,
        parent_raw: str,
        capacity: str,
        asset_type: str,
        detail: str = "",
        proposal_year: int | None = None,
        mtpa: float | None = None,
    ) -> None:
        self.detail = detail.strip()
        self.proposal_year = proposal_year
        self.mtpa = mtpa
        self.name = name.strip()
        self.country = country.strip()
        self.status = status.strip().lower()
        self.owner_raw = owner_raw.strip()
        self.parent_raw = parent_raw.strip()
        self.capacity = capacity.strip()
        self.asset_type = asset_type

    @property
    def is_expanding(self) -> bool:
        return self.status in _EXPANDING_STATUSES

    @property
    def is_operating(self) -> bool:
        return self.status in _OPERATING_STATUSES

    def is_stalled(self, year: int) -> bool:
        """Still proposed or announced more than STALLED_YEARS after it was proposed."""
        return (
            self.status in {"proposed", "announced"}
            and self.proposal_year is not None
            and year - self.proposal_year > STALLED_YEARS
        )

    @property
    def is_exiting(self) -> bool:
        return self.status in _EXITING_STATUSES

    def owner_names(self) -> list[str]:
        raw = self.parent_raw or self.owner_raw
        if not raw or raw.lower() in ("various", "unknown", ""):
            return []
        parts = re.split(r"[;,]", raw)
        names = []
        for part in parts:
            name = _SHARE.sub("", part).strip()
            if name and name.lower() not in ("various", "unknown"):
                names.append(name)
        return names

    def share_of(self, company_norm: str) -> str | None:
        """Return the company's stake in the asset as the tracker gives it, e.g. "20%".

        Args:
            company_norm: The normalised company name.

        Returns:
            The stake, or None when the tracker gives none for the company.
        """
        for part in re.split(r"[;,]", self.parent_raw or self.owner_raw or ""):
            name = _SHARE.sub("", part).strip()
            if name and _owner_matches(company_norm, name):
                found = _SHARE.search(part)
                return f"{float(found.group(1)):g}%" if found else None
        return None


# Module-level cache
_assets: list[_EGTAsset] | None = None

# An owner's stake as the tracker writes it: "BP PLC [20.00%]" or "(20%)".
_SHARE = re.compile(r"\s*[\[(]\s*(\d+(?:\.\d+)?)\s*%?\s*[\])]")


def _load() -> list[_EGTAsset]:
    global _assets
    if _assets is not None:
        return _assets

    if not _XLSX_PATH.exists():
        logger.warning(
            f"EGT Excel not found at {_XLSX_PATH}. "
            "Download from globalenergymonitor.org/projects/europe-gas-tracker/download-data/",
            extra={"operation": "egt_xlsx_missing"},
        )
        _assets = []
        return _assets

    try:
        import openpyxl
    except ImportError:
        logger.warning(
            "openpyxl not installed: cannot load EGT data.",
            extra={"operation": "egt_openpyxl_missing"},
        )
        _assets = []
        return _assets

    assets: list[_EGTAsset] = []

    try:
        wb = openpyxl.load_workbook(_XLSX_PATH, read_only=True, data_only=True)

        # --- Gas Pipelines ---
        if "Gas Pipelines" in wb.sheetnames:
            ws = wb["Gas Pipelines"]
            rows = ws.iter_rows(values_only=True)
            headers = [str(h or "").strip() for h in next(rows)]
            for row in rows:
                if len(row) < len(headers):
                    continue
                r = dict(zip(headers, row, strict=False))
                name = str(r.get("PipelineName", "") or "").strip()
                if not name:
                    continue
                # An expansion of an operating pipeline is listed as its own
                # segment; without the segment name it reads as a new pipeline.
                segment = str(r.get("SegmentName", "") or "").strip()
                if segment and segment.lower() not in name.lower():
                    name = f"{name}, {segment}"
                assets.append(
                    _EGTAsset(
                        name=name,
                        country=str(r.get("CountriesOrAreas", "") or ""),
                        status=str(r.get("Status", "") or ""),
                        owner_raw=str(r.get("Owner", "") or ""),
                        parent_raw=str(r.get("Parent", "") or ""),
                        capacity="",
                        asset_type="gas_pipeline",
                    )
                )

        # --- LNG Terminals ---
        if "LNG Terminals" in wb.sheetnames:
            ws = wb["LNG Terminals"]
            rows = ws.iter_rows(values_only=True)
            headers = [str(h or "").strip() for h in next(rows)]
            for row in rows:
                if len(row) < len(headers):
                    continue
                r = dict(zip(headers, row, strict=False))
                name = str(r.get("TerminalName", "") or "").strip()
                if not name:
                    continue
                unit = _unit(r.get("UnitName"))
                if unit and unit.lower() not in name.lower():
                    name = f"{name}, {unit}"
                facility = str(r.get("FacilityType", "") or "").strip().lower()
                capacity = _number(r.get("Capacity"))
                units = str(r.get("CapacityUnits", "") or "").strip()
                proposed = _number(r.get("ProposalYear"))
                assets.append(
                    _EGTAsset(
                        name=name,
                        country=str(r.get("Country/Area", "") or ""),
                        status=str(r.get("Status", "") or ""),
                        owner_raw=str(r.get("Owner", "") or ""),
                        parent_raw=str(r.get("Parent", "") or ""),
                        capacity=f"{capacity} {units}".strip() if capacity else "",
                        asset_type="lng_terminal",
                        proposal_year=int(float(proposed)) if proposed else None,
                        mtpa=float(_number(r.get("CapacityinMtpa")) or 0) or None,
                        detail=", ".join(
                            part
                            for part in (
                                f"{facility} terminal" if facility else "",
                                f"{capacity} {units}".strip() if capacity else "",
                                f"proposed in {proposed}" if proposed else "",
                            )
                            if part
                        ),
                    )
                )

        # --- Oil & Gas Plants ---
        if "Oil & Gas Plants" in wb.sheetnames:
            ws = wb["Oil & Gas Plants"]
            rows = ws.iter_rows(values_only=True)
            headers = [str(h or "").strip() for h in next(rows)]
            for row in rows:
                if len(row) < len(headers):
                    continue
                r = dict(zip(headers, row, strict=False))
                name = str(r.get("Plant name", "") or "").strip()
                if not name:
                    continue
                unit = _unit(r.get("Unit name"))
                if unit and unit.lower() not in name.lower():
                    name = f"{name} {unit}"
                # The sheet names its owner columns "Owner(s)" and "Parent(s)".
                owner = str(r.get("Owner(s)", "") or r.get("Owner", "") or "")
                parent = str(r.get("Parent(s)", "") or r.get("Parent", "") or "")
                capacity = _number(r.get("Capacity (MW)"))
                fuel = str(r.get("Fuel", "") or "").strip()
                assets.append(
                    _EGTAsset(
                        name=name,
                        country=str(r.get("Country/Area", "") or ""),
                        status=str(r.get("Status", "") or ""),
                        owner_raw=owner,
                        parent_raw=parent,
                        capacity=f"{capacity} MW" if capacity else "",
                        asset_type="gas_plant",
                        detail=", ".join(
                            part for part in (f"{capacity} MW" if capacity else "", fuel) if part
                        ),
                    )
                )

        wb.close()

    except Exception as exc:
        logger.warning(
            f"EGT Excel load failed: {exc}",
            extra={"operation": "egt_load_error"},
        )
        _assets = []
        return _assets

    _assets = assets
    logger.info(
        f"EGT: loaded {len(_assets)} assets "
        f"({sum(1 for a in _assets if a.asset_type == 'gas_pipeline')} pipelines, "
        f"{sum(1 for a in _assets if a.asset_type == 'lng_terminal')} LNG terminals, "
        f"{sum(1 for a in _assets if a.asset_type == 'gas_plant')} gas plants)",
        extra={"operation": "egt_loaded"},
    )
    return _assets


def _normalise(name: str) -> str:
    return name.lower().strip()


def _number(value: object) -> str:
    """Write a cell's number without a trailing ".0", or "" for an empty or text cell."""
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return ""
    return f"{number:g}" if number else ""


def _unit(value: object) -> str:
    """Name a unit: a bare number as "unit 1", any other name as the tracker writes it."""
    number = _number(value)
    return f"unit {number}" if number else str(value or "").strip()


_KINDS = {
    "gas_pipeline": ("gas pipeline segment", "gas pipeline segments"),
    "lng_terminal": ("LNG terminal unit", "LNG terminal units"),
    "gas_plant": ("gas-fired power unit", "gas-fired power units"),
}


def _count(n: int, kind: str) -> str:
    singular, plural = _KINDS.get(kind, (kind, f"{kind}s"))
    return f"{n} {singular if n == 1 else plural}"


def _assets_word(n: int) -> str:
    return f"{n} {'asset' if n == 1 else 'assets'}"


def _owner_matches(company_norm: str, owner_name: str) -> bool:
    own_norm = _normalise(owner_name)
    if names_overlap(company_norm, own_norm):
        return True
    company_first = company_norm.split()[0] if company_norm.split() else company_norm
    return len(company_first) >= 4 and contains_name(own_norm, company_first)


def _describe(asset: _EGTAsset, company_name: str, company_norm: str) -> str:
    """Name an asset with its kind, details, country, status and the company's share."""
    share = asset.share_of(company_norm)
    kind = _KINDS.get(asset.asset_type, (asset.asset_type,))[0]
    parts = [f"{kind}, {asset.detail}" if asset.detail else kind, asset.country, asset.status]
    parts.append(
        f"{company_name}'s share {share}" if share else "the tracker gives no share for the company"
    )
    return f"{asset.name} ({', '.join(part for part in parts if part)})"


def _listing(assets: list[_EGTAsset], company_name: str, company_norm: str, limit: int) -> str:
    """Describe up to limit assets and say how many more there are."""
    shown = "; ".join(_describe(a, company_name, company_norm) for a in assets[:limit])
    more = len(assets) - limit
    return shown + (f"; and {more} more" if more > 0 else "")


def stalled_lng(company_name: str) -> list[tuple[str, int, float]]:
    """Return the company's LNG terminals that are long-stalled proposals.

    Args:
        company_name: The company's name.

    Returns:
        (name, proposal year, capacity in Mtpa) for each LNG terminal unit the company
        is named on that is still proposed or announced more than STALLED_YEARS after
        it was proposed.
    """
    company_norm = _normalise(company_name)
    year = _data_year()
    found = []
    for asset in _load():
        if asset.asset_type != "lng_terminal" or not asset.is_stalled(year):
            continue
        if any(_owner_matches(company_norm, owner) for owner in asset.owner_names()):
            found.append((asset.name, asset.proposal_year or 0, asset.mtpa or 0.0))
    return found


async def fetch_egt_data(claim: Claim, company: object) -> list[Evidence]:
    """Return Europe Gas Tracker evidence for a company.

    Finds all European gas pipelines, LNG terminals, and gas plants owned
    by the company and reports expansion pipeline, operating assets, and
    retirement activity. A company owning assets in active development while
    claiming fossil gas phase-out is directly contradicted.

    Args:
        claim: The claim under assessment.
        company: The Company instance. Typed loosely to avoid circular import.

    Returns:
        A single-element list with Evidence, or empty if the company has no
        assets in the EGT or the data file is unavailable.
    """
    company_name: str = getattr(company, "name", "")
    company_norm = _normalise(company_name)

    assets = _load()
    if not assets:
        return []

    matched: list[_EGTAsset] = []
    for asset in assets:
        for owner in asset.owner_names():
            if _owner_matches(company_norm, owner):
                matched.append(asset)
                break

    if not matched:
        logger.info(
            f"EGT: no assets matched for {company_name!r}",
            extra={"operation": "egt_no_match", "company": company_name},
        )
        return []

    # New gas-fired power units burn gas; they do not supply it. They are listed apart
    # and do not count as new fossil fuel supply.
    year = _data_year()
    proposals = [a for a in matched if a.is_expanding and a.asset_type != "gas_plant"]
    stalled = [a for a in proposals if a.is_stalled(year)]
    expanding = [a for a in proposals if not a.is_stalled(year)]
    expanding_power = [a for a in matched if a.is_expanding and a.asset_type == "gas_plant"]
    operating = [a for a in matched if a.is_operating]
    exiting = [a for a in matched if a.is_exiting]

    if expanding:
        supports_claim: bool | None = False
        confidence = 0.85
    elif operating and not exiting:
        supports_claim = None
        confidence = 0.60
    elif exiting and not expanding_power:
        supports_claim = True
        confidence = 0.55
    else:
        supports_claim = None
        confidence = 0.60

    # Breakdown by type
    type_counts = {
        "gas_pipeline": sum(1 for a in matched if a.asset_type == "gas_pipeline"),
        "lng_terminal": sum(1 for a in matched if a.asset_type == "lng_terminal"),
        "gas_plant": sum(1 for a in matched if a.asset_type == "gas_plant"),
    }

    kinds = ", ".join(_count(n, kind) for kind, n in type_counts.items() if n)
    lines: list[str] = [
        f"Europe Gas Tracker (Global Energy Monitor, file of 2 March 2026): {company_name} is "
        f"named as an owner or parent of {_assets_word(len(matched))} ({kinds})."
    ]
    if expanding:
        lines.append(
            f"Gas supply infrastructure in development (proposed, announced, pre-construction "
            f"or construction): {_listing(expanding, company_name, company_norm, 5)}."
        )
    if stalled:
        lines.append(
            f"Proposed more than {STALLED_YEARS} years ago and still not past the proposal "
            f"stage, so not counted as new supply: "
            f"{_listing(stalled, company_name, company_norm, 5)}."
        )
    if expanding_power:
        lines.append(
            f"Gas-fired power units in development, which use gas rather than supply it: "
            f"{_listing(expanding_power, company_name, company_norm, 5)}."
        )
    if operating:
        lines.append(f"Operating: {_listing(operating, company_name, company_norm, 5)}.")
    if exiting:
        statuses: dict[str, int] = {}
        for asset in exiting:
            statuses[asset.status] = statuses.get(asset.status, 0) + 1
        lines.append(
            "No longer operating or not going ahead: "
            + ", ".join(f"{n} {status}" for status, n in sorted(statuses.items()))
            + "."
        )
    if not (expanding or stalled or expanding_power or operating or exiting):
        other = sorted({a.status for a in matched if a.status})
        lines.append(f"Status in the tracker: {', '.join(other) or 'not given'}.")

    summary = " ".join(lines)

    logger.info(
        f"EGT: {company_name!r}, {len(expanding)} expanding, "
        f"{len(operating)} operating, {len(exiting)} exiting",
        extra={"operation": "egt_match", "company": company_name},
    )

    raw_data: dict[str, Any] = {
        "company": company_name,
        "total_assets": len(matched),
        "expanding": len(expanding),
        "expanding_power": len(expanding_power),
        "stalled": len(stalled),
        "stalled_assets": [
            {"name": a.name, "proposal_year": a.proposal_year, "mtpa": a.mtpa} for a in stalled
        ],
        "operating": len(operating),
        "exiting": len(exiting),
        "by_type": type_counts,
        "expanding_assets": [
            {
                "name": a.name,
                "type": a.asset_type,
                "country": a.country,
                "status": a.status,
                "share": a.share_of(company_norm),
            }
            for a in expanding[:10]
        ],
        "operating_assets": [
            {
                "name": a.name,
                "type": a.asset_type,
                "country": a.country,
                "share": a.share_of(company_norm),
            }
            for a in operating[:10]
        ],
    }

    return [
        Evidence(
            claim_id=claim.id,
            trace_id=claim.trace_id,
            source=EvidenceSource.EGT,
            evidence_type=EvidenceType.VERIFIED_EMISSIONS,
            source_url="https://globalenergymonitor.org/projects/europe-gas-tracker/",
            raw_data=raw_data,
            summary=summary,
            data_year=2026,
            supports_claim=supports_claim,
            confidence=confidence,
        )
    ]

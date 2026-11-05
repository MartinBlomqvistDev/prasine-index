"""The company record: what a company does, set beside what it claims.

The record lists the evidence that describes a company as a whole: its lobbying,
its fossil fuel supply, its verified emissions, its targets, investors'
assessments and enforcement decisions. Each line states what its source says,
and the record is built in code from the evidence of a run, with no model
involved.

Two of its lines are the integrity criteria for a climate pledge set out by the
UN High-Level Expert Group on net-zero commitments: no new fossil fuel supply and
no lobbying against climate policy. The record says how many of the two the
company's records show it not meeting. It gives no score.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.evidence_scope import (
    HLEG_CITATION,
    HLEG_FOSSIL_SUPPLY,
    HLEG_LOBBYING,
    HLEG_URL,
    is_recent_finding,
)
from ingest.coal_exit import _EXPANDING_VALUES as _GCEL_EXPANDING
from ingest.gogel import _EXPANDING_VALUES as _GOGEL_EXPANDING
from ingest.lobby_map import _OBSTRUCTIVE_BANDS
from models.evidence import Evidence, EvidenceSource

__all__ = ["render_company_record"]

_OUTCOMES = {
    "BANNED": "complaint upheld",
    "CONFIRMED_MISLEADING": "finding that the advertising breached the rules",
    "FINED": "fine imposed",
    "COMMITMENTS": "commitments, without a finding of breach",
    "WARNING": "guidance or warning",
    "INVESTIGATION": "case opened, no outcome recorded",
    "NOT_UPHELD": "complaint not upheld",
    "ANNULLED": "decision annulled on appeal",
}


def _first(evidence: list[Evidence], source: EvidenceSource) -> Evidence | None:
    return next((e for e in evidence if e.source == source), None)


def _unique(evidence: Iterable[Evidence]) -> list[Evidence]:
    """Drop repeats: every claim in a run carries the same company-level records."""
    seen: set[tuple[str, str]] = set()
    unique = []
    for e in evidence:
        key = (e.source.value, e.summary)
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


def _lobbying(evidence: list[Evidence]) -> tuple[str, bool | None]:
    record = _first(evidence, EvidenceSource.LOBBY_MAP)
    if record is None:
        return "No LobbyMap record for this company.", None
    band = str(record.raw_data.get("performance_band") or "").strip()
    if not band:
        return "LobbyMap lists the company without a band.", None
    year = record.raw_data.get("year")
    obstructive = band.lower() in _OBSTRUCTIVE_BANDS
    reading = (
        "in LobbyMap's obstructive range (D to F)"
        if obstructive
        else "outside LobbyMap's obstructive range (D to F)"
    )
    when = f" ({year})" if year else ""
    return f"LobbyMap band {band}{when}, {reading}. {record.source_url}", obstructive


def _fossil_supply(evidence: list[Evidence]) -> tuple[list[str], bool | None]:
    lines: list[str] = []
    expanding = False
    seen_any = False

    gogel = _first(evidence, EvidenceSource.GOGEL)
    if gogel is not None:
        seen_any = True
        upstream = str(gogel.raw_data.get("upstream_expansion") or "").lower().strip()
        lng = str(gogel.raw_data.get("lng_expansion") or "").lower().strip()
        if upstream in _GOGEL_EXPANDING or lng in _GOGEL_EXPANDING:
            expanding = True
            lines.append(f"Global Oil and Gas Exit List: listed as expanding. {gogel.source_url}")
        else:
            lines.append(
                f"Global Oil and Gas Exit List: listed, no expansion recorded. {gogel.source_url}"
            )

    gcel = _first(evidence, EvidenceSource.COAL_EXIT)
    if gcel is not None:
        seen_any = True
        mining = str(gcel.raw_data.get("mining_expansion") or "").lower().strip()
        power = str(gcel.raw_data.get("power_expansion") or "").lower().strip()
        if mining in _GCEL_EXPANDING or power in _GCEL_EXPANDING:
            expanding = True
            lines.append(f"Global Coal Exit List: listed as expanding. {gcel.source_url}")
        else:
            lines.append(f"Global Coal Exit List: listed, no expansion recorded. {gcel.source_url}")

    for source, field, noun in (
        (EvidenceSource.GOGET, "developing", "oil and gas field(s) in development"),
        (EvidenceSource.GCPT, "expanding_units", "coal unit(s) in development"),
        (EvidenceSource.EGT, "expanding", "gas asset(s) in development"),
    ):
        record = _first(evidence, source)
        if record is None:
            continue
        seen_any = True
        count = record.raw_data.get(field)
        if isinstance(count, int) and count > 0:
            expanding = True
            lines.append(f"{record.source.value}: {count} {noun}. {record.source_url}")

    if not seen_any:
        return ["No record in the fossil fuel exit lists or asset trackers."], None
    return lines, expanding


def _emissions(evidence: list[Evidence]) -> str:
    records = [e for e in evidence if e.source == EvidenceSource.EU_ETS]
    if not records:
        return "No EU ETS installations mapped for this assessment."
    histories: list[dict[int, float]] = []
    for record in records:
        history: dict[int, float] = {}
        for row in record.raw_data.get("verified_emissions") or []:
            year, value = row.get("year"), row.get("verifiedEmissions")
            if isinstance(year, int) and isinstance(value, int | float):
                history[year] = float(value)
        if history:
            histories.append(history)
    if not histories:
        return f"EU ETS: {len(records)} installation(s) mapped, no verified emissions read."
    # Compare only years in which every mapped installation reported, so that an
    # installation joining the scheme does not read as a rise in emissions.
    common = sorted(set.intersection(*(set(h) for h in histories)))
    if len(common) < 2:
        last = max(max(h) for h in histories)
        total = sum(h.get(last, 0.0) for h in histories)
        return (
            f"EU ETS verified emissions for {len(histories)} mapped installation(s): "
            f"{total / 1e6:,.2f} Mt CO2e in {last}."
        )
    first, last = common[0], common[-1]
    start = sum(h[first] for h in histories)
    end = sum(h[last] for h in histories)
    return (
        f"EU ETS verified emissions for {len(histories)} mapped installation(s): "
        f"{end / 1e6:,.2f} Mt CO2e in {last}, against {start / 1e6:,.2f} Mt in {first}, "
        "counting years in which all of them reported."
    )


def _targets(evidence: list[Evidence]) -> str:
    record = _first(evidence, EvidenceSource.SBTI)
    if record is None:
        return "No SBTi record for this company."
    status = record.raw_data.get("status") or "unknown"
    temperature = record.raw_data.get("temp_classification") or "not classified"
    net_zero = record.raw_data.get("net_zero_status") or "none"
    return f"SBTi: status {status}, temperature classification {temperature}, net-zero target {net_zero}."


def _investors(evidence: list[Evidence]) -> list[str]:
    lines = []
    ca100 = _first(evidence, EvidenceSource.CA100)
    if ca100 is not None:
        lines.append(
            f"Climate Action 100+: Net Zero Ambition {ca100.raw_data.get('nz_ambition') or 'not assessed'}, "
            f"capex alignment {ca100.raw_data.get('capex_alignment') or 'not assessed'}."
        )
    tpi = _first(evidence, EvidenceSource.TPI)
    if tpi is not None:
        lines.append(
            f"TPI: Management Quality Level {tpi.raw_data.get('mq_level')} "
            f"({tpi.raw_data.get('mq_label')}), carbon performance 2050 "
            f"{tpi.raw_data.get('cp_alignment_2050') or 'not assessed'}."
        )
    return lines or ["No Climate Action 100+ or TPI assessment."]


def _enforcement(evidence: list[Evidence]) -> list[str]:
    records = [e for e in evidence if e.source == EvidenceSource.ENFORCEMENT]
    if not records:
        return ["No enforcement records."]
    lines = []
    for record in sorted(
        records, key=lambda e: str(e.raw_data.get("decision_date", "")), reverse=True
    ):
        outcome = _OUTCOMES.get(str(record.raw_data.get("ruling_type")), "outcome not recorded")
        recent = " Finding from the last five years." if is_recent_finding(record) else ""
        lines.append(
            f"{record.raw_data.get('authority')} {record.raw_data.get('case_reference')} "
            f"({record.raw_data.get('decision_date')}): {outcome}.{recent} {record.source_url}"
        )
    return lines


def render_company_record(evidence: Iterable[Evidence]) -> str:
    """Render the Company Record section of a company assessment.

    Args:
        evidence: The verification evidence from every claim in the run.

    Returns:
        The section body in Markdown.
    """
    records = _unique(evidence)
    lobbying, obstructive = _lobbying(records)
    fossil_lines, expanding = _fossil_supply(records)

    met = [
        name
        for name, flag in (("lobbying", obstructive), ("new fossil fuel supply", expanding))
        if flag
    ]
    unknown = [
        name
        for name, flag in (("lobbying", obstructive), ("new fossil fuel supply", expanding))
        if flag is None
    ]
    if met:
        integrity = f"The records show {len(met)} of the 2 conducts the expert group names: {' and '.join(met)}."
    else:
        integrity = "The records show neither of the 2 conducts the expert group names."
    if unknown:
        integrity += f" No record for: {' and '.join(unknown)}."

    lines = [
        "Records about the company as a whole, set beside its claims. For a climate pledge, "
        f"the {HLEG_CITATION} names two conducts a credible pledge excludes: "
        f'"{HLEG_FOSSIL_SUPPLY}" and "{HLEG_LOBBYING}" ({HLEG_URL})',
        "",
        f"**Integrity criteria for a climate pledge.** {integrity}",
        "",
        f"- **Lobbying:** {lobbying}",
        f"- **New fossil fuel supply:** {' '.join(fossil_lines)}",
        f"- **Verified emissions:** {_emissions(records)}",
        f"- **Targets:** {_targets(records)}",
        f"- **Investor assessments:** {' '.join(_investors(records))}",
        f"- **Enforcement records:** {' '.join(_enforcement(records))}",
    ]
    return "\n".join(lines)

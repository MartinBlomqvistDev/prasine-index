"""Convert urgewald's Global Coal Exit List and Global Oil & Gas Exit List to the index's CSVs.

urgewald publishes both lists as Excel workbooks (GCEL: sheet "GCEL"; GOGEL: sheet
"All Companies"), with a four-row header. This script reads the parent-company rows
and writes data/gcel_companies.csv and data/gogel_companies.csv in the columns the
ingest modules read. Each row carries a "Details" column that states the list's own
figures with the list's own labels and edition, so a summary never renames a metric.

Usage:
    python scripts/convert_urgewald_lists.py --gcel "Urgewald GCEL 2026 V1.0.xlsx" \\
        --gogel "Urgewald GOGEL 2025 V2.xlsx"
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from typing import Any

import openpyxl

_DATA = Path(__file__).parent.parent / "data"
_HEADER_ROW = 4
_EMPTY = {"", "/", "na", "n/a", "none"}


def _cell(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _number(value: Any) -> float | None:
    text = _cell(value).replace(",", "")
    if text.lower() in _EMPTY:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _rows(path: Path, sheet: str, sub_headers: bool) -> tuple[list[str], list[list[Any]]]:
    """Return a sheet's column names and its data rows.

    Both lists put the names on row four. GOGEL adds a row of sub-headers under
    grouped columns before its row of units; GCEL goes straight to the units.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet]
    rows = list(worksheet.iter_rows(values_only=True))
    header = rows[_HEADER_ROW - 1]
    below = rows[_HEADER_ROW] if sub_headers else [None] * len(header)
    names = [
        _cell(sub) or _cell(top) or f"column {index}"
        for index, (top, sub) in enumerate(zip(header, below, strict=False))
    ]
    first_data = _HEADER_ROW + (2 if sub_headers else 1)
    return names, [list(row) for row in rows[first_data:]]


def _column(names: list[str], prefix: str) -> int:
    for index, name in enumerate(names):
        if name.lower().startswith(prefix.lower()):
            return index
    raise SystemExit(f"column starting {prefix!r} not found")


def _edition(path: Path, pattern: str) -> str:
    found = re.search(pattern, path.name)
    return found.group(0) if found else path.stem


def convert_gcel(path: Path) -> int:
    """Write data/gcel_companies.csv from a GCEL workbook; return the row count."""
    names, rows = _rows(path, "GCEL", sub_headers=False)
    col = {
        "company": _column(names, "Company"),
        "hierarchy": _column(names, "Company Hierarchy"),
        "country": _column(names, "Country of Headquarters"),
        "sectors": _column(names, "Coal Industry Sectors"),
        "installed": _column(names, "Installed Coal Power Capacity"),
        "production": _column(names, "Coal Production (Annual)"),
        "power_prorated": _column(names, "Coal Power Expansion (Prorated)"),
        "power_total": _column(names, "Coal Power Expansion (Total)"),
        "power_countries": _column(names, "Coal Power Expansion Countries"),
        "mining_countries": _column(names, "Coal Mining Expansion Countries"),
    }
    edition = _edition(path, r"GCEL \d{4}")
    out = _DATA / "gcel_companies.csv"
    written = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Company",
                "Country",
                "Coal Sector",
                "Coal Mining Expansion",
                "Coal Power Expansion",
                "Coal Phase-out Plan",
                "Coal Power Capacity (GW)",
                "Details",
            ]
        )
        for row in rows:
            company = _cell(row[col["company"]])
            if not company or "Parent" not in _cell(row[col["hierarchy"]]):
                continue
            mining_countries = _cell(row[col["mining_countries"]])
            power_total = _number(row[col["power_total"]])
            power_prorated = _number(row[col["power_prorated"]])
            installed = _number(row[col["installed"]])
            production = _number(row[col["production"]])
            mining = "yes" if mining_countries.lower() not in _EMPTY else "no"
            power = "yes" if (power_total or 0) > 0 else "no"
            details = [f"{edition}"]
            if production:
                details.append(f"annual coal production {production:,.1f} Mt")
            if installed:
                details.append(f"installed coal power capacity {installed:,.0f} MW")
            if power == "yes":
                prorated = f"{power_prorated:,.0f} MW prorated, " if power_prorated else ""
                power_countries = _cell(row[col["power_countries"]])
                where = f", in {power_countries}" if power_countries.lower() not in _EMPTY else ""
                details.append(
                    f"coal power expansion {prorated}{power_total:,.0f} MW in total{where}"
                )
            if mining == "yes":
                details.append(f"coal mining expansion in {mining_countries}")
            writer.writerow(
                [
                    company,
                    _cell(row[col["country"]]),
                    _cell(row[col["sectors"]]),
                    mining,
                    power,
                    "",
                    f"{installed / 1000:.2f}" if installed else "",
                    "; ".join(details),
                ]
            )
            written += 1
    return written


def convert_gogel(path: Path) -> int:
    """Write data/gogel_companies.csv from a GOGEL workbook; return the row count."""
    names, rows = _rows(path, "All Companies", sub_headers=True)
    col = {
        "company": _column(names, "Company"),
        "hierarchy": _column(names, "Company Hierarchy"),
        "country": _column(names, "Country of Headquarters"),
        "sectors": _column(names, "Oil & Gas Subsectors"),
        "production": _column(names, "Hydrocarbons Production"),
        "development": _column(names, "Resources under Development"),
        "pipelines": _column(names, "Length of Pipelines under Development"),
        "lng": _column(names, "Total Capacity under Development"),
        "gas_power": _column(names, "Gas-Fired Power Capacity Expansion"),
    }
    edition = _edition(path, r"GOGEL \d{4}")
    out = _DATA / "gogel_companies.csv"
    written = 0
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["Company", "Country", "Sector", "Upstream Expansion", "LNG Expansion", "Details"]
        )
        for row in rows:
            company = _cell(row[col["company"]])
            if not company or "Parent" not in _cell(row[col["hierarchy"]]):
                continue
            production = _number(row[col["production"]])
            development = _number(row[col["development"]])
            pipelines = _number(row[col["pipelines"]])
            lng = _number(row[col["lng"]])
            gas_power = _number(row[col["gas_power"]])
            details = [f"{edition}"]
            if production:
                details.append(f"hydrocarbons production in 2024 {production:,.1f} mmboe")
            if development:
                details.append(
                    f"resources under development and field evaluation {development:,.1f} mmboe"
                )
            if lng:
                details.append(f"LNG capacity under development {lng:,.2f} Mtpa")
            if pipelines:
                details.append(f"pipelines under development {pipelines:,.0f} km")
            if gas_power:
                details.append(f"gas-fired power expansion {gas_power:,.0f} MW")
            writer.writerow(
                [
                    company,
                    _cell(row[col["country"]]),
                    _cell(row[col["sectors"]]),
                    "yes" if (development or 0) > 0 else "no",
                    "yes" if (lng or 0) > 0 else "no",
                    "; ".join(details),
                ]
            )
            written += 1
    return written


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gcel", type=Path, help="GCEL workbook (.xlsx)")
    parser.add_argument("--gogel", type=Path, help="GOGEL workbook (.xlsx)")
    args = parser.parse_args()
    if args.gcel:
        print(f"GCEL: {convert_gcel(args.gcel)} parent companies written")
    if args.gogel:
        print(f"GOGEL: {convert_gogel(args.gogel)} parent companies written")

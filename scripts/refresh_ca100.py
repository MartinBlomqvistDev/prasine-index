"""Refresh the Climate Action 100+ Net Zero Company Benchmark data.

CA100+ publishes each benchmark as an Excel data sheet. This script downloads the
sheet, reads its assessment tab (one row per company: the overall score of each of
the ten indicators and its change since the previous benchmark), checks that each
company's assessment page answers, and writes data/ca100_companies.csv, which
ingest/ca100.py reads. A replaced CSV is kept beside it, named by its year.

    python scripts/refresh_ca100.py
    python scripts/refresh_ca100.py --sheet-file PATH   # a data sheet already downloaded

When CA100+ publishes a new benchmark, update _DATA_SHEET_URL, _SHEET, _BENCHMARK
and _YEAR from https://www.climateaction100.org/net-zero-company-benchmark/.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import re
import shutil
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
import openpyxl

_DATA = Path(__file__).parent.parent / "data"
_DATA_SHEET_URL = (
    "https://www.climateaction100.org/wp-content/uploads/2026/10/"
    "NZB_2026_2.3_Benchmark_Downloadable_DataSheet.xlsx"
)
_SHEET = "2026 Benchmark Assessments"
_BENCHMARK = "October 2026"
_YEAR = 2026
_PAGE = "https://www.climateaction100.org/company-assessments/{slug}/"
_BENCHMARK_PAGE = "https://www.climateaction100.org/net-zero-company-benchmark/"
_USER_AGENT = (
    "Mozilla/5.0 (compatible; PrasineIndex/1.0; "
    "+https://github.com/MartinBlomqvistDev/prasine-index)"
)

# The CSV column for each benchmark indicator, by its number in the framework.
_COLUMNS = {
    1: "Net Zero Ambition Benchmark",
    2: "Long-term Target",
    3: "Medium-term Target",
    4: "Short-term Target",
    5: "Decarbonisation Strategy",
    6: "Capex Alignment",
    7: "Climate Policy Engagement",
    8: "Climate Governance",
    9: "Just Transition",
    10: "Historical Emissions Reductions",
}
_SCORES = {"Yes", "No", "Partial", "Not Applicable"}


def _cell(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _slug(name: str) -> str:
    """Return the address slug CA100+ gives a company name, e.g. "glencore-plc"."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def read_sheet(path: Path) -> list[dict[str, str]]:
    """Return one row per company from the data sheet's assessment tab.

    The tab names the indicators on one row ("Indicator 1 - ..."), the company
    columns on another ("Company name", "ISIN", ...), and puts each indicator's
    score in its first column and the change since the previous benchmark in
    the next one.
    """
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = [list(row) for row in workbook[_SHEET].iter_rows(max_col=250, values_only=True)]
    workbook.close()
    columns: dict[int, int] = {}
    for row in rows:
        for index, cell in enumerate(row):
            found = re.match(r"Indicator (\d+)\s*[-:]", _cell(cell))
            if found:
                columns.setdefault(int(found.group(1)), index)
        if len(columns) == len(_COLUMNS):
            break
    if sorted(columns) != sorted(_COLUMNS):
        raise SystemExit(f"indicator columns not found: {sorted(columns)}")
    header = next(i for i, row in enumerate(rows) if _cell(row[0]) == "Company name")
    names = [_cell(cell) for cell in rows[header]]
    isin, country, sector = (names.index(n) for n in ("ISIN", "HQ location", "Sector"))
    companies = []
    for row in rows[header + 1 :]:
        name = _cell(row[0])
        if not name or _cell(row[columns[1]]) not in _SCORES:
            continue
        record = {
            "Company": name,
            "ISIN": _cell(row[isin]),
            "HQ Country": _cell(row[country]),
            "Sector": _cell(row[sector]),
        }
        for number, column in _COLUMNS.items():
            record[column] = _cell(row[columns[number]])
            record[f"{column} Progress"] = _cell(row[columns[number] + 1])
        record.update(
            {
                "Year": str(_YEAR),
                "Benchmark": _BENCHMARK,
                "Assessment Page": "",
                "Data Sheet": _DATA_SHEET_URL,
            }
        )
        companies.append(record)
    return companies


def add_pages(companies: list[dict[str, str]], client: httpx.Client) -> int:
    """Give each company the address of its assessment page; return how many answered.

    A company whose page does not answer gets the benchmark's own page.
    """
    found = 0
    for record in companies:
        record["Assessment Page"] = _BENCHMARK_PAGE
        with contextlib.suppress(httpx.HTTPError):
            response = client.get(_PAGE.format(slug=_slug(record["Company"])))
            if response.status_code == 200:
                record["Assessment Page"] = str(response.url)
                found += 1
        time.sleep(0.3)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sheet-file", type=Path, help="a data sheet already downloaded")
    parser.add_argument("--out", type=Path, default=_DATA / "ca100_companies.csv")
    args = parser.parse_args()

    with httpx.Client(
        headers={"User-Agent": _USER_AGENT}, follow_redirects=True, timeout=60
    ) as client:
        sheet = args.sheet_file
        if sheet is None:
            response = client.get(_DATA_SHEET_URL)
            response.raise_for_status()
            sheet = Path(tempfile.mkdtemp()) / _DATA_SHEET_URL.rsplit("/", 1)[-1]
            sheet.write_bytes(response.content)
        companies = read_sheet(sheet)
        pages = add_pages(companies, client)

    if args.out.exists():
        with args.out.open(encoding="utf-8-sig") as handle:
            old_year = next(csv.DictReader(handle), {}).get("Year") or "previous"
        if old_year != str(_YEAR):
            backup = args.out.with_name(f"{args.out.stem}_{old_year}{args.out.suffix}")
            if not backup.exists():
                shutil.copy2(args.out, backup)
                print(f"kept the {old_year} file as {backup.name}")
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(companies[0]))
        writer.writeheader()
        writer.writerows(companies)
    print(
        f"{len(companies)} companies from the {_BENCHMARK} benchmark -> {args.out} "
        f"({pages} assessment pages found)"
    )


if __name__ == "__main__":
    main()

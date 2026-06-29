"""Download the Banking on Climate Chaos fossil fuel financing data.

Run this script whenever you want fresh data (report published annually in May):

    python scripts/refresh_fossil_finance.py

Banking on Climate Chaos tracks fossil fuel financing by the world's 65 largest
private-sector banks from 2016 onwards. The annual report and underlying data are
published by a coalition of NGOs including RAN, Sierra Club, and Oil Change International.

As of 2026, no bulk CSV is available for direct download. The data must be extracted
from the annual league tables PDF. For BOCC 2026, the league tables PDF is at:
  https://www.bankingonclimatechaos.org/wp-content/uploads/2026/06/BOCC26_League-Tables-OG-expansion.pdf

The NZBA membership data was added from Reclaim Finance's O&G Policy Tracker:
  https://oilgaspolicytracker.org/ (download as XLSX, use 'InFilter' column)

Saves to data/fossil_finance_banks.csv. Run refresh_cache() from ingest.fossil_finance
to reload without restarting.

CSV columns produced:
  Bank, Total Fossil Fuel Financing (USD Billion), Oil and Gas Financing ($bn),
  Net Zero Commitment, Period

Sources:
  https://www.bankingonclimatechaos.org/
  https://oilgaspolicytracker.org/
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "fossil_finance_banks.csv"

# No stable CSV download URL as of 2026 — data is extracted from the annual league tables PDF.
# For future refreshes, check the BOCC site for a companion data download. If none exists,
# download the league tables PDF and extract the first table with pdfplumber (see module docstring).
_BOCC_CSV_URL = (
    "https://www.bankingonclimatechaos.org/wp-content/themes/bocc-2021/inc/bcc-data-2024.csv"
)


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        row_count: int | str
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing file: {_DEST} ({size_kb} KB, {row_count} rows)")
    else:
        print(f"No file found at: {_DEST}")


def download_bocc_csv() -> None:
    """Attempt to download the Banking on Climate Chaos CSV."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading Banking on Climate Chaos data...")
    print(f"  URL: {_BOCC_CSV_URL}")
    print(f"  Destination: {_DEST}")

    req = urllib.request.Request(
        _BOCC_CSV_URL,
        headers={
            "User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)",
            "Accept": "text/csv,application/csv,*/*",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        print(f"\nHTTP {exc.code} — {exc.reason}")
        print_manual_instructions()
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"\nURL error: {exc.reason}")
        print_manual_instructions()
        sys.exit(1)

    if b"<html" in data[:200].lower():
        print("\nReceived HTML — URL may have changed.")
        print_manual_instructions()
        sys.exit(1)

    _DEST.write_bytes(data)
    size_kb = len(data) // 1024
    print(f"  Downloaded {size_kb} KB -> {_DEST}")

    try:
        lines = data.decode("utf-8-sig").splitlines()
        print(f"  Rows: {len(lines) - 1} banks (excluding header)")
        if lines:
            print(f"  Columns: {lines[0]}")
    except UnicodeDecodeError:
        pass

    print("Done. Run ingest.fossil_finance.refresh_cache() or restart the API to reload.")


def print_manual_instructions() -> None:
    print()
    print("Manual extraction steps (no bulk CSV available as of 2026):")
    print("  1. Download the league tables PDF from bankingonclimatechaos.org")
    print("  2. Use pdfplumber to extract Table 0 from pages 2-5 (first 65-row table)")
    print("  3. Columns: Bank, 2021, 2022, 2023, 2024, 2025, Grand Total")
    print("  4. Optionally enrich with NZBA data from oilgaspolicytracker.org")
    print(f"  5. Save as: {_DEST}")
    print()
    print("  Expected CSV columns:")
    print("    Bank, Total Fossil Fuel Financing (USD Billion),")
    print("    Oil and Gas Financing ($bn), Net Zero Commitment, Period")


if __name__ == "__main__":
    check_existing()
    download_bocc_csv()

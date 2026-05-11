"""Download the Climate Action 100+ Net Zero Company Benchmark results.

Run this script whenever you want fresh CA100+ data (updated annually at COP):

    python scripts/refresh_ca100.py

CA100+ publishes annual benchmark results for the 170 highest-emitting listed
companies at climateaction100.org/companies. The data includes net-zero ambition,
decarbonisation target alignment, capex alignment, and climate lobbying assessments.

The bulk data is available as a free CSV download from the CA100+ website.
No account required.

Saves to data/ca100_companies.csv. The pipeline reloads automatically on next
run. Run refresh_cache() from ingest.ca100 to reload without restarting.

Sources:
  https://www.climateaction100.org/companies/
  https://www.climateaction100.org/progress/net-zero-company-benchmark/
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "ca100_companies.xlsx"

# CA100+ publishes their benchmark data at this URL (may change annually).
# If this returns 404, check: https://www.climateaction100.org/progress/net-zero-company-benchmark/
# Updated to xlsx format (November 2025 release).
_CA100_XLSX_URL = (
    "https://www.climateaction100.org/wp-content/uploads/2025/12/"
    "NZB-Downloadable-Excel2025_2026_11_02.xlsx"
)


def download_ca100_csv() -> None:
    """Attempt to download the CA100+ benchmark XLSX."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading CA100+ Net Zero Benchmark XLSX...")
    print(f"  URL: {_CA100_XLSX_URL}")
    print(f"  Destination: {_DEST}")

    req = urllib.request.Request(
        _CA100_XLSX_URL,
        headers={
            "User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
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
    print("Done. Run ingest.ca100.refresh_cache() or restart the API to reload.")


def print_manual_instructions() -> None:
    print()
    print("Manual download steps:")
    print("  1. Go to https://www.climateaction100.org/progress/net-zero-company-benchmark/")
    print("  2. Click 'Download the Benchmark Data' or look for an Excel/XLSX export link")
    print(f"  3. Save to: {_DEST}")
    print()
    print("Alternative: individual company pages at https://www.climateaction100.org/companies/")


if __name__ == "__main__":
    download_ca100_csv()

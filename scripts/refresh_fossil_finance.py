"""Download the Banking on Climate Chaos fossil fuel financing data.

Run this script whenever you want fresh data (report published annually in May):

    python scripts/refresh_fossil_finance.py

Banking on Climate Chaos tracks fossil fuel financing by the world's 60 largest
private-sector banks from 2016 onwards. The annual report and underlying data are
published by a coalition of NGOs including RAN, Sierra Club, and Oil Change International.

The bulk data is available as a free CSV/Excel download from their website.
No account required.

Saves to data/fossil_finance_banks.csv. Run refresh_cache() from ingest.fossil_finance
to reload without restarting.

Sources:
  https://www.bankingonclimatechaos.org/
  https://www.bankingonclimatechaos.org/bankingonclimatechaos2024/
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "fossil_finance_banks.csv"

# Direct CSV download URL. Updated each May when the annual report is published.
# If this 404s, check: https://www.bankingonclimatechaos.org/
_BOCC_CSV_URL = (
    "https://www.bankingonclimatechaos.org/wp-content/themes/bocc-2021/inc/bcc-data-2024.csv"
)


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
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

    print(f"Downloading Banking on Climate Chaos data...")
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
    print("Manual download steps:")
    print("  1. Go to https://www.bankingonclimatechaos.org/")
    print("  2. Download the underlying data (usually a CSV or Excel file)")
    print(f"  3. Save the CSV to: {_DEST}")


if __name__ == "__main__":
    check_existing()
    download_bocc_csv()

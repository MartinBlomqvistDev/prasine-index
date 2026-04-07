"""Download the Urgewald Global Coal Exit List (GCEL).

Run this script whenever you want fresh GCEL data (updated annually at COP):

    python scripts/refresh_gcel.py

The Global Coal Exit List tracks approximately 1,000 companies across the full
coal value chain — mining, trading, transportation, and power. It is maintained
by Urgewald and a coalition of 50+ NGOs. Published free of charge, no account required.

The GCEL is the standard coal screen used by 400+ financial institutions under
the GFANZ (Glasgow Financial Alliance for Net Zero) and PAII (Paris Aligned
Investment Initiative) frameworks.

Saves to data/gcel_companies.csv. Run refresh_cache() from ingest.coal_exit to
reload without restarting.

Sources:
  https://www.urgewald.org/en/themen/global-coal-exit-list
  https://coalexit.org/
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "gcel_companies.csv"

# Urgewald makes the GCEL available at coalexit.org as a free download.
# URL updated each year (typically November, at COP).
# If this 404s check: https://coalexit.org/ or https://www.urgewald.org/gcel
_GCEL_CSV_URL = (
    "https://coalexit.org/sites/default/files/download_public/"
    "GCEL2023_PublicDownload_Nov2023.csv"
)


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing GCEL: {_DEST} ({size_kb} KB, {row_count} companies)")
    else:
        print(f"No GCEL file found at: {_DEST}")


def download_gcel_csv() -> None:
    """Attempt to download the GCEL CSV from coalexit.org."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading Global Coal Exit List CSV...")
    print(f"  URL: {_GCEL_CSV_URL}")
    print(f"  Destination: {_DEST}")

    req = urllib.request.Request(
        _GCEL_CSV_URL,
        headers={
            "User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)",
            "Accept": "text/csv,application/csv,*/*",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
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
        print(f"  Rows: {len(lines) - 1} companies (excluding header)")
        if lines:
            print(f"  Columns: {lines[0][:120]}")
    except UnicodeDecodeError:
        pass

    print("Done. Run ingest.coal_exit.refresh_cache() or restart the API to reload.")


def print_manual_instructions() -> None:
    print()
    print("Manual download steps:")
    print("  1. Go to https://coalexit.org/ or https://www.urgewald.org/gcel")
    print("  2. Download the Public GCEL CSV (free, no account required)")
    print(f"  3. Save to: {_DEST}")
    print()
    print("Alternative: check the Urgewald GCEL page for the latest release URL and")
    print("  update _GCEL_CSV_URL in this script.")


if __name__ == "__main__":
    check_existing()
    download_gcel_csv()

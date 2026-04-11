"""Download the SBTi Companies Taking Action dataset.

Run this script whenever you want fresh SBTi data:

    python scripts/refresh_sbti.py

SBTi publishes bulk data as an Excel file (no authentication required).
The file is saved to data/sbti_companies.xlsx. The pipeline loads this
automatically — ingest/sbti.py checks for xlsx if csv is absent.

Run refresh_cache() from ingest.sbti to reload without restarting the API.

Sources:
  https://sciencebasedtargets.org/companies-taking-action
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"

# SBTi bulk Excel download — confirmed working 2026-04-07, no auth required.
# If this 404s, check: https://sciencebasedtargets.org/companies-taking-action
_SBTI_XLSX_URL = "https://files.sciencebasedtargets.org/production/files/companies-excel.xlsx"
_SBTI_DEST = _DATA_DIR / "sbti_companies.xlsx"


def download_sbti() -> None:
    """Download the SBTi Companies Taking Action Excel file."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Downloading SBTi Companies Taking Action dataset...")
    print(f"  URL: {_SBTI_XLSX_URL}")
    print(f"  Destination: {_SBTI_DEST}")

    req = urllib.request.Request(
        _SBTI_XLSX_URL,
        headers={"User-Agent": "prasine-index/1.0 (greenwashing research; contact via GitHub)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        print(f"ERROR: HTTP {exc.code} - {exc.reason}")
        print(
            "URL may have changed. Check: https://sciencebasedtargets.org/companies-taking-action"
        )
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"ERROR: {exc.reason}")
        sys.exit(1)

    _SBTI_DEST.write_bytes(data)
    size_kb = len(data) // 1024
    print(f"  Downloaded {size_kb} KB -> {_SBTI_DEST}")
    print("Done. Run ingest.sbti.refresh_cache() or restart the API to reload.")
    print("Note: requires openpyxl — run: pip install openpyxl")


if __name__ == "__main__":
    download_sbti()

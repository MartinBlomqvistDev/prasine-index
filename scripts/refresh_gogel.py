"""Download the Urgewald Global Oil and Gas Exit List (GOGEL).

Run this script whenever you want fresh GOGEL data (updated annually):

    python scripts/refresh_gogel.py

The Global Oil and Gas Exit List tracks approximately 1,000 companies
responsible for the majority of global oil and gas production and development.
It covers upstream oil and gas production, LNG expansion, new licensing rounds,
and reserves development. Published by Urgewald and a coalition of NGOs.

GOGEL is the standard oil and gas screen used by 400+ financial institutions
under the GFANZ (Glasgow Financial Alliance for Net Zero) and PAII (Paris
Aligned Investment Initiative) frameworks.

Saves to data/gogel_companies.csv. Run refresh_cache() from ingest.gogel to
reload without restarting.

Sources:
  https://gogel.org/
  https://www.urgewald.org/gogel
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "gogel_companies.csv"

# Urgewald GOGEL public download URL.
# Updated annually — check https://gogel.org/ if this 404s.
# Format: GOGEL{YEAR}_PublicDownload_{MonthYear}.csv
_GOGEL_CSV_URL = (
    "https://gogel.org/sites/default/files/download_public/GOGEL2024_PublicDownload_Oct2024.csv"
)


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing GOGEL: {_DEST} ({size_kb} KB, {row_count} companies)")
    else:
        print(f"No GOGEL file found at: {_DEST}")


def download_gogel_csv() -> None:
    """Attempt to download the GOGEL CSV from gogel.org."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("\nDownloading Global Oil and Gas Exit List CSV...")
    print(f"  URL: {_GOGEL_CSV_URL}")
    print(f"  Destination: {_DEST}")

    try:
        req = urllib.request.Request(
            _GOGEL_CSV_URL,
            headers={
                "User-Agent": "PrasineIndex/1.0 (EU greenwashing monitor; "
                "contact: info@prasine.index)"
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()

        if len(data) < 500:
            raise ValueError(f"Response too small ({len(data)} bytes) — likely not a real CSV.")

        _DEST.write_bytes(data)
        size_kb = len(data) // 1024
        try:
            lines = data.decode("utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"  Saved {size_kb} KB — {row_count} companies → {_DEST}")

    except Exception as exc:
        print(f"  Download failed: {exc}")
        print(
            "\nTo get GOGEL data manually:\n"
            "  1. Go to https://gogel.org/\n"
            "  2. Download the Public Download CSV\n"
            f"  3. Save to: {_DEST}\n"
            "\nAlternatively check:\n"
            "  https://www.urgewald.org/gogel"
        )
        sys.exit(1)


def main() -> None:
    print("GOGEL data refresh")
    print("=" * 50)
    check_existing()
    download_gogel_csv()
    print("\nDone. Re-run refresh_cache() from ingest.gogel to reload.")


if __name__ == "__main__":
    main()

"""Download the InfluenceMap Company Climate Policy Engagement dataset.

Run this script whenever you want fresh InfluenceMap data:

    python scripts/refresh_influencemap.py

InfluenceMap publishes annual company-level climate lobbying scores (A+ to F)
at influencemap.org. The bulk company database is available as a free download
from their website — no account required.

The file is saved to data/influencemap_companies.csv. The pipeline reloads
automatically on next run. Run refresh_cache() from ingest.influence_map to
reload without restarting.

Sources:
  https://influencemap.org/company-responses
  https://influencemap.org/report (annual company database releases)
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "influencemap_companies.csv"

# InfluenceMap company database CSV download URL.
# InfluenceMap updates this annually; check the page below for the current URL.
# The URL below is the direct link to the bulk company scores CSV as of 2024.
# If it returns a 404, check: https://influencemap.org/company-responses
_IM_CSV_URL = (
    "https://influencemap.org/site/data/000/017/InfluenceMap_Company_Scores.csv"
)


def check_existing() -> None:
    """Report on the current state of the local InfluenceMap CSV."""
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing InfluenceMap CSV: {_DEST} ({size_kb} KB, {row_count} rows)")
    else:
        print(f"No InfluenceMap CSV found at: {_DEST}")


def download_influencemap_csv() -> None:
    """Attempt to download the InfluenceMap bulk company scores CSV."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Downloading InfluenceMap Company Scores CSV...")
    print(f"  URL: {_IM_CSV_URL}")
    print(f"  Destination: {_DEST}")

    req = urllib.request.Request(
        _IM_CSV_URL,
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
        print("\nReceived HTML — the URL may have changed or requires authentication.")
        print_manual_instructions()
        sys.exit(1)

    _DEST.write_bytes(data)
    size_kb = len(data) // 1024
    print(f"  Downloaded {size_kb} KB -> {_DEST}")

    try:
        lines = data.decode("utf-8-sig").splitlines()
        print(f"  Rows: {len(lines) - 1} companies (excluding header)")
        if lines:
            print(f"  Columns: {lines[0]}")
    except UnicodeDecodeError:
        pass

    print("Done. Run ingest.influence_map.refresh_cache() or restart the API to reload.")


def print_manual_instructions() -> None:
    """Print manual download instructions."""
    print()
    print("Manual download steps:")
    print("  1. Go to https://influencemap.org/company-responses")
    print("  2. Look for 'Download Company Scores' or 'Bulk Data Download'")
    print("  3. Download the CSV of all companies")
    print(f"  4. Save to: {_DEST}")
    print()
    print("Alternative: annual reports with company data at:")
    print("  https://influencemap.org/report")


if __name__ == "__main__":
    check_existing()
    download_influencemap_csv()

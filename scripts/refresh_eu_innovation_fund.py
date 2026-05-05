"""Download the EU Innovation Fund projects dataset.

Run this script whenever you want fresh EU Innovation Fund data:

    python scripts/refresh_eu_innovation_fund.py

The EU Innovation Fund is one of the world's largest funding programmes for
innovative low-carbon technologies in energy-intensive industries, renewable
energy, energy storage, and carbon capture and storage. Funded under the EU ETS.

Data is published by the European Commission on the EU Open Data Portal.
The dataset includes all awarded projects, grant amounts, promoters, countries,
and technology sectors.

Saves to data/eu_innovation_fund_projects.csv. Run refresh_cache() from
ingest.eu_innovation_fund to reload without restarting.

Sources:
  https://climate.ec.europa.eu/eu-action/eu-funding-climate-action/innovation-fund/projects-funded_en
  https://opendata.ec.europa.eu/dataset/innovation-fund-projects-and-grants
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "eu_innovation_fund_projects.csv"

# EC Open Data Portal — Innovation Fund projects CSV.
# If this URL returns 404, check:
#   https://opendata.ec.europa.eu/dataset/innovation-fund-projects-and-grants
# The dataset is updated after each call decision (Large-Scale, Pilots, etc.)
_EIF_CSV_URL = (
    "https://opendata.ec.europa.eu/dataset/innovation-fund-projects-and-grants/"
    "resource/download?format=csv"
)

# Fallback: direct CINEA (EC agency) CSV if open data portal URL changes
_EIF_CSV_URL_FALLBACK = (
    "https://cinea.ec.europa.eu/sites/default/files/2024-01/innovation_fund_awarded_projects.csv"
)


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
        except Exception:
            row_count = "unknown"
        print(f"Existing EU Innovation Fund data: {_DEST} ({size_kb} KB, {row_count} projects)")
    else:
        print(f"No EU Innovation Fund file found at: {_DEST}")


def download_eu_innovation_fund_csv() -> None:
    """Attempt to download the Innovation Fund CSV from the EC Open Data Portal."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    for url in (_EIF_CSV_URL, _EIF_CSV_URL_FALLBACK):
        print(f"\nAttempting download from: {url}")
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "PrasineIndex/1.0 (EU greenwashing monitor; "
                    "contact: info@prasine.index)"
                },
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()

            if len(data) < 500:
                print(f"  Response too small ({len(data)} bytes) — likely not a real CSV.")
                continue

            _DEST.write_bytes(data)
            size_kb = len(data) // 1024
            try:
                lines = data.decode("utf-8-sig").splitlines()
                row_count = len(lines) - 1
            except Exception:
                row_count = "unknown"
            print(f"  Saved {size_kb} KB — {row_count} projects → {_DEST}")
            return

        except Exception as exc:
            print(f"  Failed: {exc}")
            continue

    print(
        "\nAutomatic download failed. To get the data manually:\n"
        "  1. Go to https://climate.ec.europa.eu/eu-action/eu-funding-climate-action/"
        "innovation-fund/projects-funded_en\n"
        "  2. Download the CSV of awarded projects\n"
        f"  3. Save to: {_DEST}\n"
        "\nAlternatively, check the EC Open Data Portal:\n"
        "  https://opendata.ec.europa.eu/dataset/innovation-fund-projects-and-grants"
    )
    sys.exit(1)


def main() -> None:
    print("EU Innovation Fund data refresh")
    print("=" * 50)
    check_existing()
    download_eu_innovation_fund_csv()
    print("\nDone. Re-run refresh_cache() from ingest.eu_innovation_fund to reload.")


if __name__ == "__main__":
    main()

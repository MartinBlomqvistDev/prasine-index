"""Download the latest EU ETS daily CSV snapshots from the official Azure blob store.

Run this script whenever you want fresh data:

    python scripts/refresh_eutl.py

Files are downloaded to the EUTL24/ directory in the project root. The pipeline
picks up the new data automatically on the next run (the module-level cache is
reset after download).

Sources:
  Daily CSVs: dlsclimabi.blob.core.windows.net (Azure, official EU registry)
  Static XLSXs: climate.ec.europa.eu (European Commission)
"""

from __future__ import annotations

import gzip
import shutil
import sys
import urllib.request
from pathlib import Path

_EUTL24_DIR = Path(__file__).parent.parent / "EUTL24"

# ---------------------------------------------------------------------------
# Daily CSV snapshots (gzip-compressed, updated every day)
# ---------------------------------------------------------------------------

_DAILY_CSVS: list[tuple[str, str]] = [
    (
        "https://dlsclimabi.blob.core.windows.net/public-data/eutlpublic/extracts/_all_extracts/operators_yearly_activity/operators_yearly_activity_daily.csv.gz",
        "operators_yearly_activity_daily.csv",
    ),
    (
        "https://dlsclimabi.blob.core.windows.net/public-data/eutlpublic/extracts/_all_extracts/operator/operators_daily.csv.gz",
        "operators_daily.csv",
    ),
    (
        "https://dlsclimabi.blob.core.windows.net/public-data/eutlpublic/extracts/_all_extracts/account/accounts_daily.csv.gz",
        "accounts_daily.csv",
    ),
    (
        "https://dlsclimabi.blob.core.windows.net/public-data/eutlpublic/extracts/_all_extracts/registry_holdings/registry_holdings_daily.csv.gz",
        "registry_holdings_daily.csv",
    ),
]

# ---------------------------------------------------------------------------
# Static annual files (XLSX, updated once a year)
# Update these URLs each year when EC publishes new editions.
# ---------------------------------------------------------------------------

_STATIC_XLSX: list[tuple[str, str]] = [
    (
        "https://climate.ec.europa.eu/document/download/385daec1-0970-44ab-917d-f500658e72aa_en?filename=verified_emissions_2024_en.xlsx",
        "verified_emissions_2024_en.xlsx",
    ),
    (
        "https://climate.ec.europa.eu/document/download/b80300cf-7608-405d-969e-8b016687640e_en?filename=compliance_2024_code_en.xlsx",
        "compliance_2024_code_en.xlsx",
    ),
]


def _download_gz(url: str, dest: Path) -> None:
    """Download a .csv.gz and decompress it to dest."""
    gz_path = dest.with_suffix(".csv.gz")
    print(f"  {dest.name} ...", end=" ", flush=True)
    urllib.request.urlretrieve(url, gz_path)
    with gzip.open(gz_path, "rb") as f_in, dest.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    gz_path.unlink()
    size_mb = dest.stat().st_size / 1_048_576
    print(f"{size_mb:.1f} MB")


def _download_file(url: str, dest: Path) -> None:
    """Download a file directly (no decompression)."""
    print(f"  {dest.name} ...", end=" ", flush=True)
    urllib.request.urlretrieve(url, dest)
    size_mb = dest.stat().st_size / 1_048_576
    print(f"{size_mb:.1f} MB")


def main() -> None:
    _EUTL24_DIR.mkdir(exist_ok=True)

    print("Downloading daily CSV snapshots:")
    for url, filename in _DAILY_CSVS:
        try:
            _download_gz(url, _EUTL24_DIR / filename)
        except Exception as exc:
            print(f"  FAILED ({filename}): {exc}", file=sys.stderr)
            sys.exit(1)

    print("Downloading static XLSX files:")
    for url, filename in _STATIC_XLSX:
        try:
            _download_file(url, _EUTL24_DIR / filename)
        except Exception as exc:
            # Static files failing is non-fatal — daily CSVs are the primary source
            print(f"  WARNING ({filename}): {exc}", file=sys.stderr)

    # Reset the eu_ets module cache so the next pipeline run reads fresh data.
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).parent.parent))
        import ingest.eu_ets as eu_ets

        eu_ets.refresh_cache()
        print("EU ETS module cache reset.")
    except Exception:
        print("Note: module cache will reset automatically on next process start.")

    print("Done.")


if __name__ == "__main__":
    main()

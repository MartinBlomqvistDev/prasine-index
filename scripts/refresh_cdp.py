"""CDP corporate climate scores — access notes.

Run this script to see the current status:

    python scripts/refresh_cdp.py

---------------------------------------------------------------------------
SITUATION: CDP CORPORATE SCORES ARE NOT FREELY AVAILABLE IN BULK
---------------------------------------------------------------------------

data.cdp.net is CDP's open data portal for CITIES, STATES AND REGIONS only.
It does not contain current corporate (company) climate scores.

The only company datasets on data.cdp.net are the "Global 500 Emissions and
Response Status" series from 2011–2013 — roughly 480 companies, 12-year-old
data. Not useful for current greenwashing assessment.

Current CDP corporate A/B/C/D/F scores for thousands of companies require
one of the following:

  (a) CDP investor signatory access — free if your organisation is a
      registered investor. Sign up at: https://www.cdp.net/en/investor-signatories

  (b) CDP company account — companies can download their own data.

  (c) Purchased dataset — cdp.net/en/scores (no public pricing displayed;
      contact CDP directly).

  (d) Academic access — CDP has a research access programme.
      See: https://www.cdp.net/en/research/global-reports

---------------------------------------------------------------------------
WORKAROUND: 2013 Global 500 Dataset (free, stale)
---------------------------------------------------------------------------

The 2013 Global 500 dataset covers 482 large companies with A/B/C/D/F scores.
It is publicly accessible without login at:

  data.cdp.net → search: "2013 Global 500 Emissions and Response Status"
  → Export → CSV

This is stale (2013) but useful to verify the pipeline processes CDP evidence
correctly. Download and save to data/cdp_companies.csv to enable the ingest
module for testing.

---------------------------------------------------------------------------
PIPELINE BEHAVIOUR WITHOUT CDP DATA
---------------------------------------------------------------------------

If data/cdp_companies.csv does not exist, the ingest module returns an empty
list and logs a one-time INFO message. The pipeline continues with the other
nine sources. CDP absence is reflected in the data_gaps field of VerificationResult
and disclosed in the Judge prompt.

The pipeline is not degraded — CDP is self-reported data weighted lower than
EU ETS verified emissions. For most EU industrial companies, EU ETS + SBTi +
E-PRTR + enforcement rulings provide stronger evidence than CDP self-reporting.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEST = _DATA_DIR / "cdp_companies.csv"


def check_existing() -> None:
    if _DEST.exists():
        size_kb = _DEST.stat().st_size // 1024
        try:
            lines = _DEST.read_text(encoding="utf-8-sig").splitlines()
            row_count = len(lines) - 1
            header = lines[0] if lines else "(empty)"
        except Exception:
            row_count = "unknown"
            header = "(could not read)"
        print(f"Existing CDP CSV: {_DEST}")
        print(f"  Size: {size_kb} KB | Rows: {row_count}")
        print(f"  Columns: {header[:120]}")
    else:
        print(f"No CDP CSV found at: {_DEST}")
        print("  Pipeline will run without CDP evidence (other 9 sources active).")


if __name__ == "__main__":
    check_existing()
    print()
    print(__doc__)
    sys.exit(0)

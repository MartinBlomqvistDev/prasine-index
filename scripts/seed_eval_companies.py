"""Seed all 20 golden dataset eval companies into the companies table.

Reads EU ETS installation IDs from EUTL24/operators_daily.csv and inserts
each company with a deterministic UUID so eval cases can reference them
consistently. Safe to re-run — uses INSERT ... ON CONFLICT DO NOTHING.

Usage:
    python scripts/seed_eval_companies.py
"""

from __future__ import annotations

import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from core.database import get_session

_EUTL_OPERATORS = Path(__file__).parent.parent / "EUTL24" / "operators_daily.csv"

# ---------------------------------------------------------------------------
# Company definitions with deterministic UUIDs
# HSBC and Glencore have no EU ETS installations (bank / holding company)
# Vestas has minimal installations — included with known IDs
# ---------------------------------------------------------------------------

EVAL_COMPANIES = [
    {
        "id": "00000000-0000-0000-0000-000000000001",
        "name": "Ryanair Holdings plc",
        "country": "IE",
        "sector": "Aviation",
        "lei": None,
        "isin": "IE00BYTBXV33",
        "ticker": "RYA",
        "csrd_reporting": True,
        "name_filters": [],  # already seeded via separate script
    },
    {
        "id": "00000000-0000-0000-0000-000000000002",
        "name": "Volkswagen AG",
        "country": "DE",
        "sector": "Automotive",
        "lei": "529900HNOAA1KXQJUQ27",
        "isin": "DE0007664039",
        "ticker": "VOW3",
        "csrd_reporting": True,
        "name_filters": ["volkswagen"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000003",
        "name": "Shell plc",
        "country": "GB",
        "sector": "Oil & Gas",
        "lei": "21380068P1DRHMJ8KU70",
        "isin": "GB00BP6MXD84",
        "ticker": "SHEL",
        "csrd_reporting": True,
        "name_filters": ["shell nederland", "shell uk", "shell deutschland", "shell france",
                         "shell italia", "shell ireland", "shell aircraft", "shell energy",
                         "shell chemical", "shell refin"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000004",
        "name": "Eni SpA",
        "country": "IT",
        "sector": "Oil & Gas",
        "lei": "549300TRUWO2CD2G5692",
        "isin": "IT0003132476",
        "ticker": "ENI",
        "csrd_reporting": True,
        "name_filters": ["eni s.p.a", "eni spa", "eni uk", "agip"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000005",
        "name": "Nestlé S.A.",
        "country": "CH",
        "sector": "Food & Beverage",
        "lei": "529900F4E9IID15WZQ07",
        "isin": "CH0038863350",
        "ticker": "NESN",
        "csrd_reporting": True,
        "name_filters": ["nestle", "nestl"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000006",
        "name": "Deutsche Lufthansa AG",
        "country": "DE",
        "sector": "Aviation",
        "lei": "529900G3SW36Y7AKYK41",
        "isin": "DE0008232125",
        "ticker": "LHA",
        "csrd_reporting": True,
        "name_filters": ["lufthansa"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000007",
        "name": "HeidelbergMaterials AG",
        "country": "DE",
        "sector": "Building Materials",
        "lei": "529900DT1PXOUFTPZP36",
        "isin": "DE0006047004",
        "ticker": "HDMG",
        "csrd_reporting": True,
        "name_filters": ["heidelberg"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000008",
        "name": "TotalEnergies SE",
        "country": "FR",
        "sector": "Oil & Gas",
        "lei": "529900S21EQ1BO4ESM68",
        "isin": "FR0014000MR3",
        "ticker": "TTE",
        "csrd_reporting": True,
        "name_filters": ["totalenergies"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000009",
        "name": "HSBC Holdings plc",
        "country": "GB",
        "sector": "Banking",
        "lei": "MLU0ZO3ML4LN2LL2TL39",
        "isin": "GB0005405286",
        "ticker": "HSBA",
        "csrd_reporting": True,
        "name_filters": [],  # bank — no EU ETS installations
    },
    {
        "id": "00000000-0000-0000-0000-000000000010",
        "name": "Ørsted A/S",
        "country": "DK",
        "sector": "Utilities",
        "lei": "529900RFUGM2DGXS4R77",
        "isin": "DK0060094928",
        "ticker": "ORSTED",
        "csrd_reporting": True,
        "name_filters": ["rsted a/s", "rsted bioenergy", "rsted salg", "rsted wind", "rsted"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000011",
        "name": "BP plc",
        "country": "GB",
        "sector": "Oil & Gas",
        "lei": "IH8F083W8MVKS3KCMW29",
        "isin": "GB0007980591",
        "ticker": "BP",
        "csrd_reporting": True,
        "name_filters": ["bp exploration", "bp oil", "bp refin", "bp chemicals",
                         "bp plc", "bp europa"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000012",
        "name": "ArcelorMittal S.A.",
        "country": "LU",
        "sector": "Steel",
        "lei": "549300IB5Q0MV3NHY127",
        "isin": "LU1598757687",
        "ticker": "MT",
        "csrd_reporting": True,
        "name_filters": ["arcelormittal"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000013",
        "name": "Maersk A/S",
        "country": "DK",
        "sector": "Shipping",
        "lei": "549300NYWT6UXSS5L193",
        "isin": "DK0010244508",
        "ticker": "MAERSK-B",
        "csrd_reporting": True,
        "name_filters": ["maersk"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000014",
        "name": "Glencore plc",
        "country": "GB",
        "sector": "Mining",
        "lei": "2138002658CPO9NBH955",
        "isin": "JE00B4T3BW64",
        "ticker": "GLEN",
        "csrd_reporting": True,
        "name_filters": [],  # holding company — installations under subsidiary names
    },
    {
        "id": "00000000-0000-0000-0000-000000000015",
        "name": "Airbus SE",
        "country": "NL",
        "sector": "Aerospace",
        "lei": "549300QDGSIZB7RAPS71",
        "isin": "NL0000235190",
        "ticker": "AIR",
        "csrd_reporting": True,
        "name_filters": ["airbus"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000016",
        "name": "Unilever PLC",
        "country": "GB",
        "sector": "Consumer Goods",
        "lei": "549300WNX0WLJXSOEH28",
        "isin": "GB00B10RZP78",
        "ticker": "ULVR",
        "csrd_reporting": True,
        "name_filters": ["unilever"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000017",
        "name": "easyJet plc",
        "country": "GB",
        "sector": "Aviation",
        "lei": "2138001FXGL4JCPZLS47",
        "isin": "GB00B7KR2P84",
        "ticker": "EZJ",
        "csrd_reporting": True,
        "name_filters": ["easyjet"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000018",
        "name": "Vestas Wind Systems A/S",
        "country": "DK",
        "sector": "Renewable Energy",
        "lei": "529900IDFMEWDMBXO863",
        "isin": "DK0061539921",
        "ticker": "VWS",
        "csrd_reporting": True,
        "name_filters": ["vestas"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000019",
        "name": "Holcim Ltd",
        "country": "CH",
        "sector": "Building Materials",
        "lei": "529900HQ5YXQKHJZOB21",
        "isin": "CH0012214059",
        "ticker": "HOLN",
        "csrd_reporting": True,
        "name_filters": ["holcim", "lafargeholcim"],
    },
    {
        "id": "00000000-0000-0000-0000-000000000020",
        "name": "BP plc (VW-017 duplicate)",  # GW-017 is also VW — reuse VW id
        "country": "DE",
        "sector": "Automotive",
        "lei": None,
        "isin": None,
        "ticker": None,
        "csrd_reporting": True,
        "name_filters": [],  # reuses VW id 00000000-0000-0000-0000-000000000002
    },
]


def _load_installation_ids() -> dict[str, list[int]]:
    """Scan operators_daily.csv and return {company_id: [numeric_inst_ids]}."""
    id_map: dict[str, list[int]] = {c["id"]: [] for c in EVAL_COMPANIES}

    if not _EUTL_OPERATORS.exists():
        print(f"WARNING: {_EUTL_OPERATORS} not found — seeding without installation IDs")
        return id_map

    with _EUTL_OPERATORS.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("ACCOUNT_HOLDER_NAME", "").lower()
            inst_raw = row.get("INSTALLATION_IDENTIFIER", "").strip()
            if not inst_raw:
                continue
            try:
                inst_id = int(inst_raw)
            except ValueError:
                continue

            for company in EVAL_COMPANIES:
                filters = company["name_filters"]
                if filters and any(f in name for f in filters):
                    id_map[company["id"]].append(inst_id)

    return id_map


async def seed() -> None:
    id_map = _load_installation_ids()

    # Ryanair is already seeded with correct IDs — skip it
    ryanair_id = "00000000-0000-0000-0000-000000000001"

    # GW-017 reuses VW (same company) — skip the placeholder entry
    skip_ids = {ryanair_id, "00000000-0000-0000-0000-000000000020"}

    async with get_session() as session:
        for company in EVAL_COMPANIES:
            cid = company["id"]
            if cid in skip_ids:
                continue

            installation_ids = id_map.get(cid, [])
            # Convert numeric IDs back to string format (plain numeric, no prefix)
            inst_json = json.dumps([str(i) for i in installation_ids])

            await session.execute(
                text("""
                    INSERT INTO companies (
                        id, name, lei, isin, ticker, country, sector,
                        eu_ets_installation_ids, csrd_reporting
                    ) VALUES (
                        :id, :name, :lei, :isin, :ticker, :country, :sector,
                        :eu_ets_installation_ids, :csrd_reporting
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        eu_ets_installation_ids = EXCLUDED.eu_ets_installation_ids,
                        updated_at = NOW()
                """),
                {
                    "id": cid,
                    "name": company["name"],
                    "lei": company.get("lei"),
                    "isin": company.get("isin"),
                    "ticker": company.get("ticker"),
                    "country": company["country"],
                    "sector": company["sector"],
                    "eu_ets_installation_ids": inst_json,
                    "csrd_reporting": company["csrd_reporting"],
                },
            )
            print(f"  Seeded: {company['name']} — {len(installation_ids)} installations")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())

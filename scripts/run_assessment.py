"""Run the Prasine Index pipeline against a real company claim.

Usage:
    python scripts/run_assessment.py --company "Shell plc" --claim "Shell is on track
    to become a net-zero energy business by 2050" --url "https://shell.com/sustainability"

Saves a markdown report to docs/reports/<slug>.md and prints the verdict.
Costs ~$0.05 per run on Haiku defaults.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from agents.extraction_agent import ExtractionInput
from core.database import get_session, init_db, teardown_db
from core.pipeline import Pipeline, PipelineConfig
from models.claim import SourceType

_REPORTS_DIR = Path(__file__).parent.parent / "docs" / "reports"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


async def _ensure_company(company_name: str, company_id: uuid.UUID) -> None:
    async with get_session() as session:
        await session.execute(
            text("""
                INSERT INTO companies (id, name, country, sector)
                VALUES (:id, :name, 'EU', 'Corporate')
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": str(company_id), "name": company_name},
        )
        await session.commit()


async def run(company_name: str, claim_text: str, source_url: str) -> None:
    await init_db()

    company_id = uuid.uuid5(uuid.NAMESPACE_DNS, company_name.lower())
    await _ensure_company(company_name, company_id)

    pipeline = Pipeline(config=PipelineConfig())

    try:
        extraction_input = ExtractionInput(
            trace_id=uuid.uuid4(),
            company_id=company_id,
            source_url=source_url,
            source_type=SourceType.PRESS_RELEASE,
            raw_content=claim_text,
        )

        results = await pipeline.run_from_document(extraction_input)

        if not results:
            print("No claims extracted — check the input text.")
            return

        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        for r in results:
            slug = _slug(company_name)
            out_path = _REPORTS_DIR / f"{slug}.md"
            out_path.write_text(r.report or "No report generated.", encoding="utf-8")

            print(f"\n{'='*60}")
            print(f"Company : {company_name}")
            print(f"Verdict : {r.score.verdict.value}")
            print(f"Score   : {r.score.score:.0f}/100")
            print(f"Report  : {out_path}")
            print(f"{'='*60}\n")

    finally:
        await pipeline.aclose()
        await teardown_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Prasine Index pipeline on a single claim.")
    parser.add_argument("--company", required=True, help="Company name")
    parser.add_argument("--claim", required=True, help="The green claim text to assess")
    parser.add_argument("--url", required=True, help="Source URL of the claim")
    args = parser.parse_args()

    asyncio.run(run(args.company, args.claim, args.url))

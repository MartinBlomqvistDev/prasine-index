"""Check for new enforcement actions against indexed companies.

Searches EC press releases and key national authority sites (ACM, ASA, CMA)
for each company in the Prasine Index. Writes hits since the last run to
data/enforcement_flags.json. Exits 0 always — failures are logged, not fatal.

Usage:
    python scripts/refresh_enforcement.py

Requires ANTHROPIC_API_KEY in environment (uses claude-haiku-4-5-20251001
with web search; costs ~$0.02 per company per run).
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_FLAGS_FILE = _DATA_DIR / "enforcement_flags.json"
_STATE_FILE = _DATA_DIR / "enforcement_last_run.json"

_COMPANIES: list[str] = [
    "BP plc",
    "RWE AG",
    "Danone SA",
    "Eni SpA",
    "SSAB AB",
    "IKEA Group",
    "Enel SpA",
    "H&M Group",
    "Securitas AB",
    "Glencore plc",
    "Ørsted A/S",
    "KLM Royal Dutch Airlines",
    "Wizz Air Holdings plc",
    "Ryanair Holdings plc",
    "LKAB",
    "Öresundskraft",
    "Stegra",
    "TotalEnergies SE",
]

_SEARCH_SOURCES = [
    "site:ec.europa.eu/commission/presscorner",
    "site:acm.nl",
    "site:asa.org.uk/rulings",
    "site:competitionandmarkets.gov.uk",
]

_SYSTEM_PROMPT = """\
You are a regulatory monitoring assistant. Given a company name and recent \
search results, identify any enforcement actions, regulatory rulings, \
settlements, or investigations concluded or announced since the given date. \
Return ONLY a JSON object with these fields:
  "has_new_action": bool,
  "actions": list of {"date": "YYYY-MM-DD or approx", "authority": str, "summary": str, "url": str}
If nothing new, return {"has_new_action": false, "actions": []}.\
"""


def _load_last_run() -> str:
    if _STATE_FILE.exists():
        state: dict[str, str] = json.loads(_STATE_FILE.read_text())
        return state.get("last_run", "2025-01-01")
    return "2025-01-01"


def _save_last_run() -> None:
    _DATA_DIR.mkdir(exist_ok=True)
    _STATE_FILE.write_text(
        json.dumps({"last_run": datetime.date.today().isoformat()}),
        encoding="utf-8",
    )


def _check_company(
    company: str,
    since: str,
    client: object,
) -> dict[str, object]:
    query = (
        f'"{company}" greenwashing OR enforcement OR ruling OR settlement OR investigation '
        f"after:{since} " + " OR ".join(_SEARCH_SOURCES)
    )

    try:
        response = client.messages.create(  # type: ignore[attr-defined]
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Company: {company}\n"
                        f"Check for new enforcement actions since: {since}\n"
                        f"Search query to use: {query}"
                    ),
                }
            ],
        )

        for block in response.content:
            if hasattr(block, "type") and block.type == "text":
                text: str = getattr(block, "text", "").strip()
                if text.startswith("{"):
                    result: dict[str, object] = json.loads(text)
                    return result

        return {"has_new_action": False, "actions": []}

    except Exception as exc:
        return {"has_new_action": False, "actions": [], "error": str(exc)}


def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[SKIP] ANTHROPIC_API_KEY not set — skipping enforcement check")
        return

    try:
        import anthropic
    except ImportError:
        print("[SKIP] anthropic package not available")
        return

    client = anthropic.Anthropic(api_key=api_key)
    since = _load_last_run()
    today = datetime.date.today().isoformat()

    print(f"Checking enforcement actions since {since} for {len(_COMPANIES)} companies...")

    flags: list[dict[str, object]] = []

    for company in _COMPANIES:
        result = _check_company(company, since, client)
        if result.get("has_new_action"):
            actions: list[dict[str, str]] = result.get("actions", [])  # type: ignore[assignment]
            flags.append({"company": company, "checked": today, "actions": actions})
            print(f"  [FLAG] {company}: {len(actions)} new action(s)")
            for a in actions:
                print(
                    f"         {a.get('date', '?')} — {a.get('authority', '?')}: {a.get('summary', '')[:80]}"
                )
        else:
            err = result.get("error")
            if err:
                print(f"  [ERR ] {company}: {err}")
            else:
                print(f"  [  OK] {company}: nothing new")

    _DATA_DIR.mkdir(exist_ok=True)
    existing: list[dict[str, object]] = []
    if _FLAGS_FILE.exists():
        existing = json.loads(_FLAGS_FILE.read_text())

    existing.extend(flags)
    _FLAGS_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    _save_last_run()

    if flags:
        print(
            f"\n{len(flags)} companies flagged. Review data/enforcement_flags.json before next assessment run."
        )
    else:
        print(f"\nNo new enforcement actions found since {since}.")


if __name__ == "__main__":
    main()

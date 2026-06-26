"""Run all data-source refresh scripts sequentially and log results.

Usage:
    python scripts/refresh_all.py

Logs to logs/refresh_YYYY-MM-DD.log. Exits 0 if all scripts succeed,
1 if any fail. Wire this single script into Windows Task Scheduler —
do not schedule individual refresh_*.py scripts.
"""

from __future__ import annotations

import datetime
import importlib.util
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent
_LOGS_DIR = _SCRIPTS_DIR.parent / "logs"

_REFRESH_SCRIPTS: list[str] = [
    "refresh_eutl.py",
    "refresh_eprtr.py",
    "refresh_sbti.py",
    "refresh_cdp.py",
    "refresh_lobbymap.py",
    "refresh_ca100.py",
    "refresh_gcel.py",
    "refresh_fossil_finance.py",
    "refresh_gogel.py",
    "refresh_eu_innovation_fund.py",
    "refresh_eea_national.py",
    "refresh_eu_transparency_register.py",
    "refresh_gcpt.py",
    "refresh_egt.py",
    "refresh_goget.py",
    "refresh_enforcement.py",
]

_ENTRY_POINTS: tuple[str, ...] = (
    "download_sbti",
    "download_LobbyMap_csv",
    "download_ca100_csv",
    "main",
    "download_bocc_csv",
    "download_gcel_csv",
    "run",
)


def _run_script(script_name: str) -> tuple[bool, str]:
    path = _SCRIPTS_DIR / script_name
    if not path.exists():
        return False, "file not found"

    spec = importlib.util.spec_from_file_location("_refresh", path)
    if spec is None or spec.loader is None:
        return False, "could not load module"

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        for fn_name in _ENTRY_POINTS:
            fn = getattr(module, fn_name, None)
            if fn is not None:
                fn()
                return True, "ok"
        return False, "no known entry point found"
    except SystemExit as exc:
        code = exc.code
        if code == 0 or code is None:
            return True, "ok (sys.exit 0)"
        return False, f"sys.exit({code})"
    except Exception as exc:
        return False, str(exc)


def main() -> None:
    _LOGS_DIR.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    log_path = _LOGS_DIR / f"refresh_{today}.log"

    results: list[tuple[str, bool, str]] = []

    with log_path.open("w", encoding="utf-8") as log:

        def emit(line: str) -> None:
            print(line)
            log.write(line + "\n")

        emit(f"=== refresh_all started {datetime.datetime.now().isoformat()} ===\n")

        for script_name in _REFRESH_SCRIPTS:
            ok, detail = _run_script(script_name)
            tag = "[OK  ]" if ok else "[FAIL]"
            emit(f"  {tag} {script_name:<45} {detail}")
            results.append((script_name, ok, detail))

        failures = [r for r in results if not r[1]]
        emit(f"\n=== {len(results) - len(failures)}/{len(results)} scripts succeeded ===")
        if failures:
            emit("FAILED:")
            for name, _, detail in failures:
                emit(f"  {name}: {detail}")
        emit(f"Log: {log_path}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()

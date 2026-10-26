"""Record tests, three local runtime observations, and one negative case.

Run from any directory. Outputs contain no host name, user path, or credentials.
This records software evidence, not robot or physical-network measurements.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prime_components.core import load_json, write_json
from prime_components.portfolio import choose_portfolio
from prime_components.runtime import run_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "local-evidence")
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    test = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                          cwd=ROOT, capture_output=True, text=True, timeout=90)
    (out / "tests.txt").write_text(test.stdout + test.stderr, encoding="utf-8")
    if test.returncode:
        print("Tests failed; see tests.txt", file=sys.stderr)
        return 1
    runs = []
    for index in range(1, 4):
        report = run_experiment()
        write_json(out / f"run-{index:02d}.json", report)
        if not report["all_correct"]:
            print(f"Observation {index} failed; its report was preserved", file=sys.stderr)
            return 1
        runs.append(report)
    negative = run_experiment(workers=2, tasks=2, iterations=100, timeout_s=10,
                              fail_all_workers=True)
    write_json(out / "all-workers-unavailable.json", negative)
    fault = negative["scenarios"]["multi_worker_failure"]
    if (negative["all_correct"] or fault.get("reason") != "no_live_workers_after_injected_failure"
            or "task-0000" in fault["results"]):
        print("Negative case did not exercise the intended incomplete task", file=sys.stderr)
        return 1
    write_json(out / "portfolio.json", choose_portfolio(load_json(ROOT / "examples" / "portfolio.json")))
    sources = sorted([*ROOT.glob("prime_components/*.py"), *ROOT.glob("tests/*.py"), Path(__file__)])
    summary = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "real local processes; synthetic work; no hardware or general speedup conclusion",
        "parameters": {"workers": 3, "tasks": 12, "iterations_per_task": 20000},
        "environment": runs[0]["environment"], "runs": len(runs), "all_runs_correct": True,
        "source_hash_encoding": "UTF-8 text, BOM removed and newlines normalized to LF",
        "source_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(
                              p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").encode("utf-8")).hexdigest()
                          for p in sources},
        "scenario_wall_s": {},
        "recovery_to_first_retry_s": [r["scenarios"]["multi_worker_failure"]["failure_to_first_retry_success_s"]
                                      for r in runs],
        "negative_case": fault["reason"],
    }
    for name in runs[0]["scenarios"]:
        values = [r["scenarios"][name]["wall_s"] for r in runs]
        summary["scenario_wall_s"][name] = {
            "observations": values, "median": statistics.median(values),
            "min": min(values), "max": max(values),
        }
    write_json(out / "summary.json", summary)
    print(json.dumps({"runs": len(runs), "all_runs_correct": True,
                      "negative_case": summary["negative_case"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

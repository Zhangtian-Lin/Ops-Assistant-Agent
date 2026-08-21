"""Run every deterministic verification target and write an auditable CI manifest."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SUMMARY = REPORTS / "ci_verification_latest.json"

TARGETS = (
    ("regression", "scripts/run_verification.py", "latest_verification.json"),
    ("intent_smoke_eval", "scripts/run_intent_eval.py", "intent_eval_latest.json"),
    ("rag_eval", "scripts/run_rag_eval.py", "rag_eval_latest.json"),
    ("tool_skill_eval", "scripts/run_tool_engineering_tests.py", "tool_engineering_latest.json"),
    ("agent_e2e_eval_200", "scripts/run_agent_eval.py", "agent_eval_latest.json"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    for _, _, report_name in TARGETS:
        path = REPORTS / report_name
        if path.exists():
            path.unlink()
    if SUMMARY.exists():
        SUMMARY.unlink()

    records = []
    for name, script, report_name in TARGETS:
        started = time.perf_counter()
        completed = subprocess.run([sys.executable, script], cwd=ROOT, check=False)
        report = REPORTS / report_name
        records.append({
            "name": name,
            "command": f"{Path(sys.executable).name} {script}",
            "exit_code": completed.returncode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "report": report_name,
            "report_present": report.is_file(),
            "report_sha256": sha256(report) if report.is_file() else None,
            "passed": completed.returncode == 0 and report.is_file(),
        })

    successful = all(record["passed"] for record in records)
    payload = {
        "report_name": "CI verification evidence manifest",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "successful": successful,
        "environment": {
            "python": sys.version.split()[0],
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "github_sha": os.getenv("GITHUB_SHA"),
            "github_ref": os.getenv("GITHUB_REF"),
            "github_event_name": os.getenv("GITHUB_EVENT_NAME"),
        },
        "summary": {
            "targets": len(records),
            "passed": sum(record["passed"] for record in records),
            "failed": sum(not record["passed"] for record in records),
        },
        "records": records,
    }
    SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())

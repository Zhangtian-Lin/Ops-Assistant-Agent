"""运行 Tool/Skill 工程证据测试并输出独立 JSON 报告。"""

import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE_ROOT))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from scripts.run_verification import RecordingRunner
import unittest


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_tool_engineering")
    result = RecordingRunner(verbosity=2).run(suite)
    report = {
        "报告名称": "Tool 与 Skill 工程可靠性证据",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "summary": {
            "tests_run": result.testsRun,
            "passed": result.testsRun - len(result.failures) - len(result.errors),
            "failures": len(result.failures),
            "errors": len(result.errors),
            "successful": result.wasSuccessful(),
        },
        "records": result.records,
    }
    path = WORKSPACE_ROOT / "reports" / "tool_engineering_latest.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Tool engineering report written to {path}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

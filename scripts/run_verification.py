"""Run the showcase verification suite and write a machine-readable result."""

import json
import os
import platform
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = WORKSPACE_ROOT / "reports"
REPORT_FILE = REPORT_DIR / "latest_verification.json"
# Keep NumPy/OpenBLAS from creating many worker threads in constrained CI environments.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, str(WORKSPACE_ROOT))


class RecordingResult(unittest.TextTestResult):
    def startTest(self, test):
        self._started_at = time.perf_counter()
        super().startTest(test)

    def _record(self, test, outcome, detail=""):
        self.records.append({
            "test": test.id(),
            "outcome": outcome,
            "duration_ms": round((time.perf_counter() - self._started_at) * 1000, 2),
            "detail": detail,
            "证据": getattr(test, "evidence", None),
        })

    def addSuccess(self, test):
        self._record(test, "passed")
        super().addSuccess(test)

    def addFailure(self, test, err):
        self._record(test, "failed", self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addError(self, test, err):
        self._record(test, "error", self._exc_info_to_string(err, test))
        super().addError(test, err)


class RecordingRunner(unittest.TextTestRunner):
    resultclass = RecordingResult

    def _makeResult(self):
        result = super()._makeResult()
        result.records = []
        return result


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(WORKSPACE_ROOT / "tests"), top_level_dir=str(WORKSPACE_ROOT))
    result = RecordingRunner(verbosity=2).run(suite)
    REPORT_DIR.mkdir(exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "summary": {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "successful": result.wasSuccessful()},
        "records": result.records,
    }
    REPORT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verification report written to {REPORT_FILE}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

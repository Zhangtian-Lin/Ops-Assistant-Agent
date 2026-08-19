"""Run deterministic intent-routing evaluation and save per-case evidence."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE_ROOT))

from agent import route_task

SOURCE = WORKSPACE_ROOT / "tests" / "fixtures" / "intent_eval.jsonl"
TARGET = WORKSPACE_ROOT / "reports" / "intent_eval_latest.json"


def main() -> int:
    cases = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line.strip()]
    records = []
    correct = 0
    for case in cases:
        routed = route_task(case["input"])
        expected = case["expected_tool"]
        actual = routed["tool"]
        passed = actual == expected
        correct += passed
        records.append({"输入": case["input"], "预期工具": expected, "实际工具": actual, "通过": passed})
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "offline_rule_fallback",
        "summary": {"cases": len(records), "correct": correct, "intent_accuracy": round(correct / len(records), 4)},
        "records": records,
    }
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0 if correct == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())

import json
from collections import Counter
from pathlib import Path

from tests.evidence import EvidenceTestCase


class AgentEvalDatasetTests(EvidenceTestCase):
    def test_dataset_has_exact_versioned_distribution(self):
        source = Path(__file__).parent / "fixtures" / "agent_eval_cases.jsonl"
        cases = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        expected = {
            "明确只读请求": 40, "模糊自然语言": 35, "非法参数": 25, "高风险与越权": 30,
            "Prompt Injection": 25, "Tool故障与超时": 20, "无答案或需要追问": 15, "多步骤请求": 10,
        }
        self.assertEqual(len(cases), 200)
        self.assertEqual(Counter(case["category"] for case in cases), expected)
        self.assertEqual(len({case["id"] for case in cases}), 200)
        for case in cases:
            self.assertIn("input", case)
            self.assertIn("expected", case)
            self.assertIn("tool", case["expected"])
            self.assertIn("status", case["expected"])
        self.record_evidence({"fixture": str(source)}, expected, {"cases": len(cases), "distribution": dict(Counter(case["category"] for case in cases))})

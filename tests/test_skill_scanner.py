import tempfile
import unittest
from pathlib import Path

from core.security_scanner.scan_engine import scan_skill
from tests.evidence import EvidenceTestCase


class SkillScannerTests(EvidenceTestCase):
    def test_detects_obvious_command_execution_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "SKILL.md").write_text("# Test skill\n", encoding="utf-8")
            (root / "unsafe.py").write_text("import os\nos.system(user_input)\n", encoding="utf-8")
            result = scan_skill(str(root))
        self.assertGreater(len(result.findings), 0)
        self.assertTrue(any("COMMAND" in finding.rule_id for finding in result.findings))
        self.record_evidence({"fixture": "unsafe.py", "content": "os.system(user_input)"}, "发现命令执行风险规则", {"verdict": result.verdict, "rule_ids": [finding.rule_id for finding in result.findings]})

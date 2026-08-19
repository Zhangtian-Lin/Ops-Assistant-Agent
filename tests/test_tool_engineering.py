import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from core.skills.lifecycle import SkillLifecycle, SkillLifecycleError
from core.tools.executor import ToolExecutor
from core.tools.models import ToolDefinition, ToolRequest
from core.tools.registry import ToolRegistrationError, ToolRegistry
from tests.evidence import EvidenceTestCase


EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
OBJECT = {"type": "object"}


def definition(handler, **overrides):
    values = {
        "name": "demo",
        "description": "test tool",
        "handler": handler,
        "input_schema": EMPTY,
        "output_schema": OBJECT,
        "risk": "low",
        "execution_mode": "direct",
        "required_permissions": ("system.read",),
        "timeout_seconds": 1,
    }
    values.update(overrides)
    return ToolDefinition(**values)


class ToolEngineeringTests(EvidenceTestCase):
    def execute(self, item, arguments=None, permissions=("system.read",)):
        registry = ToolRegistry()
        registry.register(item)
        return ToolExecutor(registry).execute(ToolRequest(item.name, arguments or {}, permissions, "trace-test"))

    def test_unknown_tool_is_denied(self):
        result = ToolExecutor(ToolRegistry()).execute(ToolRequest("run_powershell", {}, (), "trace-unknown"))
        self.assertEqual(result.error_code, "TOOL_UNKNOWN")
        self.assertEqual(result.policy_decision, "deny")
        self.record_evidence({"tool": "run_powershell"}, "未知工具拒绝且处理函数不运行", result.to_dict())

    def test_schema_rejects_extra_arguments(self):
        result = self.execute(definition(lambda: {"ok": True}), {"command": "whoami"})
        self.assertEqual(result.error_code, "ARG_SCHEMA_INVALID")
        self.record_evidence({"tool": "demo", "arguments": {"command": "whoami"}}, "Schema 拒绝额外字段", result.to_dict())

    def test_permission_is_required(self):
        result = self.execute(definition(lambda: {"ok": True}), permissions=())
        self.assertEqual(result.error_code, "PERMISSION_DENIED")
        self.record_evidence({"permissions": []}, "缺少权限时拒绝执行", result.to_dict())

    def test_timeout_is_classified(self):
        result = self.execute(definition(lambda: (time.sleep(0.2), {"ok": True})[1], timeout_seconds=0.1))
        self.assertEqual(result.error_code, "TOOL_TIMEOUT")
        self.record_evidence({"timeout_seconds": 0.1}, "超时被归类且 Agent 及时返回", result.to_dict())

    def test_handler_failure_and_invalid_output_are_classified(self):
        def fail():
            raise RuntimeError("sensitive internal detail")

        failed = self.execute(definition(fail))
        invalid = self.execute(definition(lambda: ["not", "object"]))
        self.assertEqual(failed.error_code, "TOOL_EXECUTION_FAILED")
        self.assertNotIn("sensitive", failed.message or "")
        self.assertEqual(invalid.error_code, "RESULT_SCHEMA_INVALID")
        self.record_evidence({}, "异常脱敏且非法输出被拒绝", {"exception": failed.to_dict(), "invalid_output": invalid.to_dict()})

    def test_high_risk_direct_registration_is_rejected(self):
        with self.assertRaises(ToolRegistrationError):
            ToolRegistry().register(definition(lambda: {}, risk="high", execution_mode="direct"))
        self.record_evidence({"risk": "high", "mode": "direct"}, "注册阶段拒绝高风险直接执行", {"registration": "rejected"})

    def test_skill_requires_scan_and_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "candidate"
            source.mkdir()
            (source / "SKILL.md").write_text("# Safe demo\nRead-only example.\n", encoding="utf-8")
            (source / "manifest.json").write_text('{"name":"safe-demo","version":"1.0.0","author":"test","permissions":{"network":false,"filesystem":false,"subprocess":false},"resources":[],"depends_on":[],"sandbox_policy":"read-only","signature":"test-fixture"}', encoding="utf-8")
            with patch("core.skills.lifecycle.SKILL_ROOT", root / "state"), patch("core.skills.lifecycle.STAGING_ROOT", root / "state" / "staging"), patch("core.skills.lifecycle.INSTALLED_ROOT", root / "state" / "installed"), patch("core.skills.lifecycle.STATE_FILE", root / "state" / "lifecycle.json"):
                lifecycle = SkillLifecycle()
                found = lifecycle.discover(str(source))
                with self.assertRaises(SkillLifecycleError):
                    lifecycle.install(found["candidate_id"])
                scanned = lifecycle.scan(found["candidate_id"])
                with self.assertRaises(SkillLifecycleError):
                    lifecycle.confirm(found["candidate_id"], "yes")
                confirmed = lifecycle.confirm(found["candidate_id"], scanned["confirmation_phrase"])
                installed = lifecycle.install(found["candidate_id"])
        self.assertEqual(installed["state"], "installed")
        self.record_evidence({"candidate_id": found["candidate_id"], "wrong_confirmation": "yes"}, "必须扫描通过并输入绑定摘要的确认短语后才能安装", {"scanned": scanned["scan"], "confirmed_state": confirmed["state"], "installed_state": installed["state"]})

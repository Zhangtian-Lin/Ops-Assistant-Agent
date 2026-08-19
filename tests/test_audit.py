import json
import tempfile
from pathlib import Path

from core import approvals, audit
from tests.evidence import EvidenceTestCase


class _MemoryWriter:
    def __init__(self, fail=False):
        self.fail = fail
        self.events = []

    def write(self, event):
        if self.fail:
            raise OSError("simulated_event_log_unavailable")
        self.events.append(event)


class AuditPipelineTests(EvidenceTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.previous_approvals = approvals.RUNTIME_DIR, approvals.DB_PATH, approvals.LEGACY_FILE
        self.previous_audit = audit.RUNTIME_DIR, audit.AUDIT_KEY_PATH
        approvals.RUNTIME_DIR, approvals.DB_PATH, approvals.LEGACY_FILE = root / "runtime", root / "runtime" / "approvals.db", root / "legacy.json"
        audit.RUNTIME_DIR, audit.AUDIT_KEY_PATH = root / "runtime", root / "runtime" / "audit_hmac.key"
        approvals.initialize()

    def tearDown(self):
        approvals.RUNTIME_DIR, approvals.DB_PATH, approvals.LEGACY_FILE = self.previous_approvals
        audit.RUNTIME_DIR, audit.AUDIT_KEY_PATH = self.previous_audit
        self.temp_dir.cleanup()

    def test_trace_is_preserved_and_sensitive_actor_is_redacted(self):
        trace_id = "trc-0123456789abcdef"
        created = approvals.create_request("clear_session_history", {"requester": "operator-a"}, "windows-sid:S-1-5-21-sensitive", trace_id=trace_id)
        writer = _MemoryWriter()
        result = approvals.deliver_audit_outbox(writer)
        self.assertEqual(result, {"delivered": 1, "failed": 0})
        event = writer.events[0]
        serialized = json.dumps(event, ensure_ascii=False)
        self.assertEqual(event["trace_id"], trace_id)
        self.assertNotIn("S-1-5-21-sensitive", serialized)
        self.assertTrue(event["actor_ref"].startswith("actor-hmac:"))
        self.record_evidence(
            {"trace_id": trace_id, "actor": "windows-sid:S-1-5-21-sensitive"},
            "投递事件保留 trace_id，且不包含原始 Windows SID",
            {"delivered": result["delivered"], "trace_id": event["trace_id"], "actor_ref": event["actor_ref"]},
        )

    def test_failed_eventlog_delivery_stays_in_outbox_for_retry(self):
        approvals.create_request("clear_session_history", {"requester": "operator-a"}, "operator-a", trace_id="trc-abcdefghijklmnop")
        failed = approvals.deliver_audit_outbox(_MemoryWriter(fail=True))
        pending = approvals.list_outbox_events(delivered=False)
        self.assertEqual(failed, {"delivered": 0, "failed": 1})
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["attempts"], 1)
        successful = approvals.deliver_audit_outbox(_MemoryWriter())
        self.assertEqual(successful, {"delivered": 1, "failed": 0})
        self.record_evidence(
            {"fault": "模拟 Windows Event Log 不可写"},
            "事件保留在 SQLite outbox，恢复后恰好投递一次",
            {"first_delivery": failed, "pending_after_failure": len(pending), "retry_delivery": successful},
        )

    def test_sanitized_preview_hides_secret_and_user_profile(self):
        raw = r"token=super-secret-value C:\Users\Linzt\private.txt"
        sanitized = audit.sanitize_text(raw)
        self.assertNotIn("super-secret-value", sanitized)
        self.assertNotIn("Linzt", sanitized)
        self.assertIn("[REDACTED]", sanitized)
        self.record_evidence(
            {"input_contains": ["token", "Windows user profile"]},
            "日志预览移除令牌值与用户目录名",
            {"sanitized_preview": sanitized},
        )

import concurrent.futures
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import approvals
from tests.evidence import EvidenceTestCase


class ApprovalStateMachineTests(EvidenceTestCase):
    """Use an isolated SQLite database; never touch the live approval store."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous = approvals.RUNTIME_DIR, approvals.DB_PATH, approvals.LEGACY_FILE
        approvals.RUNTIME_DIR = Path(self.temp_dir.name) / "runtime"
        approvals.DB_PATH = approvals.RUNTIME_DIR / "approvals.db"
        approvals.LEGACY_FILE = Path(self.temp_dir.name) / "legacy.json"
        approvals.initialize()

    def tearDown(self):
        approvals.RUNTIME_DIR, approvals.DB_PATH, approvals.LEGACY_FILE = self.previous
        self.temp_dir.cleanup()

    def _create(self):
        created = approvals.create_request("clear_session_history", {"requester": "operator-a"}, "operator-a")
        self.assertEqual(created["status"], "pending")
        return created["request"]["request_id"]

    def test_valid_lifecycle_is_audited(self):
        request_id = self._create()
        self.assertEqual(approvals.approve_request(request_id, "approver-b")["status"], "approved")
        self.assertEqual(approvals.claim_execution(request_id, "executor")["status"], "executing")
        self.assertEqual(approvals.complete_execution(request_id, {"cleared": True})["status"], "executed")
        events = approvals.list_audit_events(request_id)
        self.assertEqual([event["event_type"] for event in events], ["created", "approved", "executing", "executed"])
        self.record_evidence({"action": "clear_session_history", "requester": "operator-a", "approver": "approver-b"}, "状态依次为 pending、approved、executing、executed，且写入四条审计事件", {"events": [event["event_type"] for event in events]})

    def test_tampered_snapshot_is_failed_before_approval(self):
        request_id = self._create()
        connection = sqlite3.connect(approvals.DB_PATH)
        try:
            connection.execute("UPDATE approval_requests SET details_json = ? WHERE request_id = ?", ('{"requester":"attacker"}', request_id))
            connection.commit()
        finally:
            connection.close()
        outcome = approvals.approve_request(request_id, "approver-b")
        self.assertEqual(outcome["status"], "integrity_error")
        self.assertEqual(approvals.get_request(request_id)["status"], "failed")
        self.record_evidence({"operation": "直接在测试数据库中篡改 details_json"}, "审批前发现快照摘要不一致并失败", {"approve_status": outcome["status"], "request_status": approvals.get_request(request_id)["status"]})

    def test_expired_request_cannot_be_approved(self):
        request_id = self._create()
        connection = sqlite3.connect(approvals.DB_PATH)
        try:
            connection.execute("UPDATE approval_requests SET expires_at = ? WHERE request_id = ?", ("2000-01-01T00:00:00Z", request_id))
            connection.commit()
        finally:
            connection.close()
        outcome = approvals.approve_request(request_id, "approver-b")
        self.assertEqual(outcome["status"], "invalid_state")
        self.assertEqual(outcome["current_status"], "expired")
        self.record_evidence({"operation": "将测试请求 expires_at 改为 2000-01-01"}, "过期请求不可审批", outcome)

    def test_concurrent_execution_claim_has_exactly_one_winner(self):
        request_id = self._create()
        self.assertEqual(approvals.approve_request(request_id, "approver-b")["status"], "approved")
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(lambda _: approvals.claim_execution(request_id, "executor"), range(20)))
        self.assertEqual(sum(item["status"] == "executing" for item in outcomes), 1)
        self.assertTrue(all(item["status"] in {"executing", "invalid_state"} for item in outcomes))
        self.assertEqual(approvals.complete_execution(request_id, {"cleared": True})["status"], "executed")
        self.assertEqual(approvals.claim_execution(request_id, "executor")["status"], "invalid_state")
        self.record_evidence({"request_id": "测试生成", "concurrent_claims": 20}, "恰好一个执行者领取请求；完成后不能再次领取", {"executing_winners": sum(item["status"] == "executing" for item in outcomes), "other_outcomes": sorted({item["status"] for item in outcomes}), "final_status": "executed"})

import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.network import checks, policy
from tests.evidence import EvidenceTestCase


class NetworkPolicyTests(EvidenceTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_policy_file = policy.POLICY_FILE
        policy.POLICY_FILE = Path(self.temp_dir.name) / "network_policy.yaml"

    def tearDown(self):
        policy.POLICY_FILE = self.previous_policy_file
        self.temp_dir.cleanup()

    def write_policy(self, text):
        policy.POLICY_FILE.write_text(text, encoding="utf-8")

    def test_missing_policy_denies_external_tcp(self):
        result = checks.check_tcp("example.com", 443)
        self.assertEqual(result["status"], "network_error")
        self.assertIn("allowed_hosts", result["error"])
        self.record_evidence({"policy": "缺失", "target": "example.com", "port": 443}, "拒绝外部 TCP", result)

    def test_unallowlisted_host_is_denied_before_resolution(self):
        self.write_policy("network:\n  allowed_hosts: [allowed.example]\n  allowed_ports: [443]\n")
        with patch("core.network.checks.socket.getaddrinfo") as resolver:
            result = checks.check_tcp("blocked.example", 443)
        self.assertEqual(result["status"], "network_error")
        resolver.assert_not_called()
        self.record_evidence({"policy": {"allowed_hosts": ["allowed.example"]}, "target": "blocked.example", "port": 443}, "白名单外主机在 DNS 解析前被拒绝", {"result": result, "resolver_called": resolver.called})

    def test_public_address_is_rejected_after_dns_resolution(self):
        self.write_policy("network:\n  allowed_hosts: [allowed.example]\n  allowed_ports: [443]\n  allow_private_addresses: true\n  allow_public_addresses: false\n")
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with patch("core.network.checks.socket.getaddrinfo", return_value=records):
            result = checks.check_tcp("allowed.example", 443)
        self.assertEqual(result["status"], "network_error")
        self.assertIn("public", result["error"])
        self.record_evidence({"policy": {"allow_public_addresses": False}, "mock_dns_result": "8.8.8.8"}, "解析到公网地址后阻断连接", result)

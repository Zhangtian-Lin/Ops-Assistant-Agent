"""Run a documented test layer without relying on a third-party test runner."""

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GROUPS = {
    "unit": ["tests.test_approvals", "tests.test_llm_client", "tests.test_tool_engineering", "tests.test_rag"],
    "integration": ["tests.test_runtime", "tests.test_llm_setup"],
    "security": ["tests.test_audit", "tests.test_network_policy", "tests.test_routing_security", "tests.test_skill_scanner"],
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=sorted(GROUPS))
    args = parser.parse_args()
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in GROUPS[args.group])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

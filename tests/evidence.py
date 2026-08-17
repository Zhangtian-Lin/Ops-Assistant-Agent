import unittest


class EvidenceTestCase(unittest.TestCase):
    """A unittest base class that exposes human-readable evidence to the report runner."""

    def record_evidence(self, input_data, expected, observed):
        self.evidence = {
            "输入": input_data,
            "预期": expected,
            "实际观察": observed,
        }

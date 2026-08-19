import tempfile
from pathlib import Path

import yaml

from scripts.configure_llm import OLLAMA_MODEL, provider_config, write_config
from tests.evidence import EvidenceTestCase


class LLMSetupTests(EvidenceTestCase):
    def test_ollama_config_is_local_keyless_and_no_download_occurs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "llm.yaml"
            write_config("ollama", path)
            config = yaml.safe_load(path.read_text(encoding="utf-8"))["llm"]
        self.assertEqual(config["provider"], "ollama")
        self.assertEqual(config["base_url"], "http://127.0.0.1:11434/v1")
        self.assertEqual(config["model"], OLLAMA_MODEL)
        self.assertEqual(config["api_key_env"], "")
        self.record_evidence(
            {"mode": "ollama", "operation": "仅生成隔离配置"},
            "写入本机无 Key 配置，不在配置阶段自动下载模型",
            {"provider": config["provider"], "base_url": config["base_url"], "model": config["model"], "key_required": False},
        )

    def test_rules_mode_keeps_agent_available_without_llm(self):
        config = provider_config("rules")["llm"]
        self.assertFalse(config["enabled"])
        self.assertEqual(config["model"], "")
        self.record_evidence(
            {"mode": "rules"},
            "允许不配置模型，确定性工具继续可用",
            {"enabled": config["enabled"], "model": config["model"]},
        )

    def test_cloud_modes_store_variable_name_not_secret(self):
        openai = provider_config("openai")["llm"]
        groq = provider_config("groq")["llm"]
        volcengine = provider_config("volcengine")["llm"]
        serialized = yaml.safe_dump({"openai": openai, "groq": groq, "volcengine": volcengine})
        self.assertEqual(openai["api_key_env"], "OPS_AGENT_LLM_API_KEY")
        self.assertEqual(groq["api_key_env"], "GROQ_API_KEY")
        self.assertEqual(volcengine["api_key_env"], "ARK_API_KEY")
        self.assertNotIn("sk-", serialized)
        self.assertNotIn("gsk_", serialized)
        self.record_evidence(
            {"modes": ["openai", "groq", "volcengine"]},
            "配置只保存环境变量名，不保存真实 Key",
            {"openai_key_env": openai["api_key_env"], "groq_key_env": groq["api_key_env"], "volcengine_key_env": volcengine["api_key_env"]},
        )

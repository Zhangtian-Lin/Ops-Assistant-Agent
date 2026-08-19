import json
import os
import unittest
import urllib.error
from unittest.mock import patch

from core.intent_parser import INTENT_JSON_SCHEMA, parse_intent, parse_with_llm
from core.llm.client import LLMClient, LLMConfig
from tests.evidence import EvidenceTestCase


def _payload(value):
    return {"model": "test-model", "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}, "choices": [{"message": {"content": json.dumps(value)}}]}


class LLMEngineeringTests(EvidenceTestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPS_AGENT_LLM_API_KEY": "test-secret"}, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.config = LLMConfig(enabled=True, model="test-model", max_retries=1, timeout_seconds=0.1)

    def test_schema_bound_result_exposes_metrics_without_secret(self):
        client = LLMClient(self.config, transport=lambda *_: _payload({"action": "check", "object": "disk", "args": {"path": "C:\\"}, "confidence": 0.98}))
        result = client.complete_json("system", "check disk", {"type": "object"})
        self.assertTrue(result.ok)
        self.assertEqual(result.data["object"], "disk")
        self.assertEqual(result.metrics["total_tokens"], 18)
        self.assertNotIn("test-secret", json.dumps(result.metrics))
        self.record_evidence({"input": "检查 C 盘"}, "成功返回结构化结果与 token 指标，指标不泄露 API Key", {"ok": result.ok, "metrics": result.metrics})

    def test_groq_provider_uses_same_bounded_client_contract(self):
        config = LLMConfig(
            enabled=True,
            provider="groq",
            base_url="https://api.groq.com/openai/v1",
            model="openai/gpt-oss-20b",
            api_key_env="GROQ_API_KEY",
            max_retries=0,
        )
        observed = {}
        def transport(base_url, api_key, body, timeout):
            observed.update({"base_url": base_url, "api_key": api_key, "model": body["model"], "strict": body["response_format"]["json_schema"]["strict"]})
            return _payload({"action": "check", "object": "cpu", "args": {}, "confidence": 0.96})
        with patch.dict(os.environ, {"GROQ_API_KEY": "groq-test-secret"}, clear=False):
            result = LLMClient(config, transport=transport).complete_json("system", "检查 CPU", {"type": "object"})
        self.assertTrue(result.ok)
        self.assertEqual(observed["base_url"], "https://api.groq.com/openai/v1")
        self.assertEqual(observed["model"], "openai/gpt-oss-20b")
        self.assertTrue(observed["strict"])
        self.assertNotIn("groq-test-secret", json.dumps(result.metrics))
        self.record_evidence(
            {"provider": "groq", "model": observed["model"]},
            "Groq 使用官方兼容地址和严格 schema，密钥不进入指标",
            {"base_url": observed["base_url"], "strict": observed["strict"], "ok": result.ok},
        )

    def test_ollama_needs_no_key_and_uses_json_object_mode(self):
        config = LLMConfig(enabled=True, provider="ollama", base_url="http://127.0.0.1:11434/v1", model="qwen3:4b", api_key_env="", max_retries=0)
        observed = {}
        def transport(base_url, api_key, body, timeout):
            observed.update({"base_url": base_url, "api_key": api_key, "response_format": body["response_format"]})
            return _payload({"action": "check", "object": "cpu", "args": {}, "confidence": 0.91})
        result = LLMClient(config, transport=transport).complete_json("system", "电脑有点卡", {"type": "object"})
        self.assertTrue(result.ok)
        self.assertIsNone(observed["api_key"])
        self.assertEqual(observed["response_format"], {"type": "json_object"})
        self.record_evidence(
            {"provider": "ollama", "base_url": observed["base_url"]},
            "本地 Provider 不读取 Key，并使用 Ollama 支持的 JSON Object 模式",
            {"ok": result.ok, "api_key_used": False, "response_format": observed["response_format"]},
        )

    def test_ollama_rejects_non_loopback_endpoint(self):
        config = LLMConfig(enabled=True, provider="ollama", base_url="http://example.com:11434/v1", model="qwen3:4b", api_key_env="")
        result = LLMClient(config, transport=lambda *_: self.fail("transport must not be called")).complete_json("system", "query", {})
        self.assertEqual(result.error_code, "unsafe_local_endpoint")
        self.record_evidence(
            {"provider": "ollama", "base_url": "http://example.com:11434/v1"},
            "本地模式只能连接 127.0.0.1/localhost:11434",
            {"error_code": result.error_code},
        )

    def test_volcengine_uses_ark_endpoint_key_name_and_json_mode(self):
        config = LLMConfig(enabled=True, provider="volcengine", base_url="https://ark.cn-beijing.volces.com/api/v3", model="doubao-seed-2-1-turbo-260628", api_key_env="ARK_API_KEY", max_retries=0)
        observed = {}
        def transport(base_url, api_key, body, timeout):
            observed.update({"base_url": base_url, "api_key": api_key, "model": body["model"], "response_format": body["response_format"]})
            return _payload({"action": "check", "object": "cpu", "args": {}, "confidence": 0.93})
        with patch.dict(os.environ, {"ARK_API_KEY": "ark-test-secret"}, clear=False):
            result = LLMClient(config, transport=transport).complete_json("system", "电脑有点卡", {"type": "object"})
        self.assertTrue(result.ok)
        self.assertEqual(observed["base_url"], "https://ark.cn-beijing.volces.com/api/v3")
        self.assertEqual(observed["response_format"], {"type": "json_object"})
        self.assertNotIn("ark-test-secret", json.dumps(result.metrics))
        self.record_evidence(
            {"provider": "volcengine", "model": observed["model"]},
            "火山方舟使用国内官方地址、环境变量 Key 和兼容 JSON 模式",
            {"base_url": observed["base_url"], "response_format": observed["response_format"], "ok": result.ok},
        )

    def test_timeout_retries_then_rules_take_over(self):
        calls = []
        def timeout(*_):
            calls.append(1)
            raise TimeoutError()
        client = LLMClient(self.config, transport=timeout)
        result = client.complete_json("system", "check cpu", {"type": "object"})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "timeout")
        self.assertEqual(len(calls), 2)
        fallback = parse_intent("检查 CPU", lambda _: ("check", "cpu"))
        self.assertEqual(fallback["source"], "rules")
        self.record_evidence({"fault": "LLM 连续超时"}, "重试一次后不阻塞 Agent，回退规则路由", {"attempts": result.metrics["attempts"], "error_code": result.error_code, "fallback_source": fallback["source"]})

    def test_low_confidence_and_extra_arguments_do_not_expand_tool_power(self):
        low_confidence = LLMClient(self.config, transport=lambda *_: _payload({"action": "check", "object": "disk", "args": {}, "confidence": 0.2}))
        self.assertIsNone(parse_with_llm("检查磁盘", low_confidence))
        with patch("core.intent_parser.parse_with_llm", return_value={"action": "check", "object": "disk", "args": {"path": "C:\\", "command": "del /s"}, "confidence": 0.99}):
            parsed = parse_intent("检查 C 盘", lambda _: (None, None))
        self.assertEqual(parsed["args"], {"path": "C:\\"})
        self.record_evidence({"model_output": "低置信度，或带 command 额外字段"}, "低置信度回退；未声明参数 command 被丢弃", {"low_confidence_source": "rules", "clean_args": parsed["args"]})

    def test_missing_api_key_never_calls_transport(self):
        called = []
        with patch.dict(os.environ, {}, clear=True):
            result = LLMClient(self.config, transport=lambda *_: called.append(1)).complete_json("s", "u", {})
        self.assertEqual(result.error_code, "missing_api_key")
        self.assertEqual(called, [])
        self.record_evidence({"configuration": "启用 LLM 但未设置 API Key"}, "不发起网络调用，规则路由可继续工作", {"error_code": result.error_code, "transport_called": False})

    def test_strict_intent_schema_closes_nested_args_object(self):
        args_schema = INTENT_JSON_SCHEMA["properties"]["args"]
        self.assertFalse(args_schema["additionalProperties"])
        self.assertEqual(set(args_schema["required"]), set(args_schema["properties"]))
        self.assertIn("none", INTENT_JSON_SCHEMA["properties"]["object"]["enum"])
        self.record_evidence(
            {"schema": "intent.args"},
            "严格 schema 禁止额外参数，并为无法判断提供 none 对象",
            {"additional_properties": args_schema["additionalProperties"], "required_fields": args_schema["required"]},
        )

    def test_invalid_content_reports_safe_finish_reason_without_raw_text(self):
        payload = {"model": "test-model", "choices": [{"finish_reason": "length", "message": {"content": "{truncated"}}]}
        result = LLMClient(self.config, transport=lambda *_: payload).complete_json("system", "query", {"type": "object"})
        self.assertEqual(result.error_code, "invalid_json_content")
        self.assertEqual(result.diagnostics, {"finish_reason": "length", "content_length": 10})
        self.assertNotIn("truncated", json.dumps(result.diagnostics))
        self.record_evidence(
            {"response": "模拟被长度限制截断的 JSON"},
            "诊断区分 JSON 截断，只记录结束原因与长度，不记录原文",
            {"error_code": result.error_code, "diagnostics": result.diagnostics},
        )

    def test_http_error_exposes_code_but_never_provider_message(self):
        body = json.dumps({"error": {"type": "permissions_error", "code": "region_blocked", "message": "sensitive provider details"}}).encode()
        error = urllib.error.HTTPError("https://example.invalid", 403, "Forbidden", {}, __import__('io').BytesIO(body))
        result = LLMClient(self.config, transport=lambda *_: (_ for _ in ()).throw(error)).complete_json("system", "query", {})
        serialized = json.dumps(result.diagnostics)
        self.assertEqual(result.diagnostics["provider_error_code"], "region_blocked")
        self.assertNotIn("sensitive provider details", serialized)
        self.record_evidence(
            {"http_status": 403, "provider_body": "包含 code/type/message"},
            "只保留机器错误 code/type，不记录服务商 message",
            result.diagnostics,
        )

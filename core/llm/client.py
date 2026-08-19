"""Small, dependency-free OpenAI-compatible JSON completion client."""

import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = WORKSPACE_ROOT / "config" / "llm.yaml"


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = ""
    api_key_env: str = "OPS_AGENT_LLM_API_KEY"
    timeout_seconds: float = 12.0
    max_retries: int = 1
    max_output_tokens: int = 180


@dataclass(frozen=True)
class LLMResult:
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    diagnostics: Optional[Dict[str, Any]] = None


def load_llm_config(path: Path = CONFIG_PATH) -> LLMConfig:
    """Load non-secret local configuration. Missing config means LLM is disabled."""
    if not path.exists():
        return LLMConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raw = raw.get("llm", raw)
        if not isinstance(raw, dict):
            return LLMConfig()
        allowed = {name: raw[name] for name in LLMConfig.__dataclass_fields__ if name in raw}
        return LLMConfig(**allowed)
    except (OSError, yaml.YAMLError, TypeError, ValueError):
        return LLMConfig()


class LLMClient:
    """Calls one configured OpenAI-compatible endpoint with bounded retry behavior."""

    def __init__(self, config: Optional[LLMConfig] = None, transport: Optional[Callable[..., Dict[str, Any]]] = None):
        self.config = config or load_llm_config()
        self.transport = transport or self._http_transport

    def complete_json(self, system_prompt: str, user_input: str, schema: Dict[str, Any]) -> LLMResult:
        started = time.perf_counter()
        cfg = self.config
        if not cfg.enabled:
            return self._result(False, "disabled", started)
        if cfg.provider not in {"openai_compatible", "groq", "volcengine", "ollama"} or not cfg.model:
            return self._result(False, "invalid_config", started)
        if cfg.provider == "ollama" and not self._is_safe_ollama_url(cfg.base_url):
            return self._result(False, "unsafe_local_endpoint", started)
        api_key = os.getenv(cfg.api_key_env) if cfg.api_key_env else None
        if cfg.provider != "ollama" and not api_key:
            return self._result(False, "missing_api_key", started)
        body = {
            "model": cfg.model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_input}],
            "temperature": 0,
            "max_tokens": cfg.max_output_tokens,
            "response_format": (
                {"type": "json_object"}
                if cfg.provider in {"ollama", "volcengine"}
                else {"type": "json_schema", "json_schema": {"name": "ops_agent_intent", "strict": True, "schema": schema}}
            ),
        }
        last_error = "request_failed"
        last_diagnostics: Dict[str, Any] = {}
        last_payload: Optional[Dict[str, Any]] = None
        for attempt in range(cfg.max_retries + 1):
            try:
                payload = self.transport(cfg.base_url, api_key, body, cfg.timeout_seconds)
                last_payload = payload if isinstance(payload, dict) else None
                if not isinstance(payload, dict):
                    last_error, last_diagnostics = "invalid_response_shape", {"stage": "response_envelope"}
                    raise _RetryableResponseError()
                choices = payload.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    last_error, last_diagnostics = "missing_choices", {"stage": "response_envelope"}
                    raise _RetryableResponseError()
                choice = choices[0]
                message = choice.get("message")
                if not isinstance(message, dict):
                    last_error, last_diagnostics = "missing_message", {"finish_reason": choice.get("finish_reason")}
                    raise _RetryableResponseError()
                content = message.get("content")
                if content is None and message.get("refusal"):
                    return self._result(False, "model_refusal", started, payload, attempt, diagnostics={"finish_reason": choice.get("finish_reason")})
                if not isinstance(content, str) or not content.strip():
                    last_error = "empty_content"
                    last_diagnostics = {"finish_reason": choice.get("finish_reason")}
                    raise _RetryableResponseError()
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    last_error = "invalid_json_content"
                    last_diagnostics = {"finish_reason": choice.get("finish_reason"), "content_length": len(content)}
                    raise _RetryableResponseError()
                if not isinstance(parsed, dict):
                    return self._result(False, "invalid_json_shape", started, payload, attempt, diagnostics={"json_type": type(parsed).__name__})
                return self._result(True, None, started, payload, attempt, parsed)
            except TimeoutError:
                last_error = "timeout"
                last_diagnostics = {"stage": "transport"}
            except urllib.error.HTTPError as exc:
                last_error = "http_error"
                last_diagnostics = self._safe_http_error_diagnostics(exc)
                # Authentication, permission and request-schema errors do not improve on retry.
                if 400 <= exc.code < 500 and exc.code != 429:
                    return self._result(False, last_error, started, attempt=attempt, diagnostics=last_diagnostics)
            except urllib.error.URLError as exc:
                last_error = "transport_error"
                last_diagnostics = {"reason_type": type(exc.reason).__name__, "stage": "transport"}
            except _RetryableResponseError:
                pass
            except (TypeError, ValueError):
                last_error = "invalid_response"
                last_diagnostics = {"stage": "unknown"}
            if attempt < cfg.max_retries:
                time.sleep(0.15 * (2 ** attempt))
        return self._result(False, last_error, started, last_payload, cfg.max_retries, diagnostics=last_diagnostics)

    @staticmethod
    def _safe_http_error_diagnostics(exc: urllib.error.HTTPError) -> Dict[str, Any]:
        """Expose only machine-readable fields; never copy the provider's message."""
        result: Dict[str, Any] = {"http_status": exc.code, "stage": "transport"}
        try:
            body = json.loads(exc.read().decode("utf-8"))
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                for source, target in (("type", "provider_error_type"), ("code", "provider_error_code")):
                    value = error.get(source)
                    if isinstance(value, str) and len(value) <= 80:
                        result[target] = value
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        return result

    @staticmethod
    def _is_safe_ollama_url(base_url: str) -> bool:
        """Local mode must never silently become an arbitrary remote endpoint."""
        try:
            parsed = urlparse(base_url)
        except ValueError:
            return False
        return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port == 11434

    @staticmethod
    def _http_transport(base_url: str, api_key: Optional[str], body: Dict[str, Any], timeout_seconds: float) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _result(ok: bool, error_code: Optional[str], started: float, payload: Optional[Dict[str, Any]] = None, attempt: int = 0, data: Optional[Dict[str, Any]] = None, diagnostics: Optional[Dict[str, Any]] = None) -> LLMResult:
        usage = (payload or {}).get("usage") or {}
        metrics = {
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "attempts": attempt + 1,
            "model": (payload or {}).get("model"),
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }
        return LLMResult(ok=ok, data=data, error_code=error_code, metrics=metrics, diagnostics=diagnostics or {})


class _RetryableResponseError(RuntimeError):
    """Internal control flow; never exposed with response content."""

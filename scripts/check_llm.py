"""Make one safe intent request and print diagnostics without secrets or raw output."""

import json
import os
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE_ROOT))

from core.intent_parser import INTENT_JSON_SCHEMA, INTENT_SYSTEM_PROMPT
from core.llm import LLMClient, load_llm_config


def main() -> int:
    config = load_llm_config()
    key_required = config.provider != "ollama"
    key_present = bool(os.getenv(config.api_key_env)) if config.api_key_env else False
    summary = {
        "enabled": config.enabled,
        "provider": config.provider,
        "base_url": config.base_url,
        "model": config.model,
        "api_key_env": config.api_key_env,
        "api_key_required": key_required,
        "api_key_present": key_present,
    }
    if not config.enabled or (key_required and not key_present) or not config.model:
        summary["ok"] = False
        summary["error_code"] = "configuration_incomplete"
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    result = LLMClient(config).complete_json(
        INTENT_SYSTEM_PROMPT,
        "检查 CPU 使用率",
        INTENT_JSON_SCHEMA,
    )
    summary.update({"ok": result.ok, "error_code": result.error_code, "diagnostics": result.diagnostics, "metrics": result.metrics})
    if result.ok and result.data:
        summary["parsed_intent"] = {
            "action": result.data.get("action"),
            "object": result.data.get("object"),
            "confidence": result.data.get("confidence"),
        }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

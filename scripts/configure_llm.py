"""First-run LLM provider setup. Downloads occur only after explicit confirmation."""

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

import yaml

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = WORKSPACE_ROOT / "config" / "llm.yaml"
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:4b"
OLLAMA_MODEL_SIZE = "约 2.5 GB"


def provider_config(mode: str) -> Dict[str, Any]:
    common = {"enabled": True, "timeout_seconds": 12, "max_retries": 1, "max_output_tokens": 180}
    if mode == "ollama":
        return {"llm": {**common, "provider": "ollama", "base_url": f"{OLLAMA_BASE_URL}/v1", "model": OLLAMA_MODEL, "api_key_env": "", "timeout_seconds": 30, "max_retries": 0}}
    if mode == "openai":
        return {"llm": {**common, "provider": "openai_compatible", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_env": "OPS_AGENT_LLM_API_KEY"}}
    if mode == "groq":
        return {"llm": {**common, "provider": "groq", "base_url": "https://api.groq.com/openai/v1", "model": "openai/gpt-oss-20b", "api_key_env": "GROQ_API_KEY"}}
    if mode == "volcengine":
        return {"llm": {**common, "provider": "volcengine", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "model": "doubao-seed-2-1-turbo-260628", "api_key_env": "ARK_API_KEY"}}
    if mode == "rules":
        return {"llm": {"enabled": False, "provider": "openai_compatible", "base_url": "https://api.openai.com/v1", "model": "", "api_key_env": "OPS_AGENT_LLM_API_KEY", "timeout_seconds": 12, "max_retries": 1, "max_output_tokens": 180}}
    raise ValueError("Unsupported LLM mode")


def write_config(mode: str, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(provider_config(mode), allow_unicode=True, sort_keys=False), encoding="utf-8")


def ollama_status() -> Dict[str, Any]:
    status = {"installed": bool(shutil.which("ollama")), "service_ready": False, "model_ready": False, "model": OLLAMA_MODEL}
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/version", timeout=1.5) as response:
            version = json.loads(response.read().decode("utf-8"))
        status.update({"service_ready": True, "version": version.get("version")})
        with urllib.request.urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
            models = json.loads(response.read().decode("utf-8")).get("models", [])
        names = {item.get("name") or item.get("model") for item in models if isinstance(item, dict)}
        status["model_ready"] = OLLAMA_MODEL in names or f"{OLLAMA_MODEL}:latest" in names
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        pass
    return status


def pull_ollama_model() -> int:
    executable = shutil.which("ollama")
    if not executable:
        print("Ollama 尚未安装，不能下载模型。")
        return 2
    print(f"即将下载 {OLLAMA_MODEL}（{OLLAMA_MODEL_SIZE}）。")
    return subprocess.run([executable, "pull", OLLAMA_MODEL], check=False).returncode


def interactive_setup() -> int:
    print("\n请选择 LLM 模式：")
    print(f"1) 本地 Ollama（推荐、免费；首次需安装并下载 {OLLAMA_MODEL_SIZE} 模型）")
    print("2) OpenAI 云 API（用户自带 Key，可能收费）")
    print("3) Groq 云 API（免费限额；部分地区不可用）")
    print("4) 火山方舟云 API（国内可用，用户自带 Key）")
    print("5) 不使用 LLM（规则路由仍可用）")
    choice = input("请输入 1、2、3、4 或 5：").strip()
    mode = {"1": "ollama", "2": "openai", "3": "groq", "4": "volcengine", "5": "rules"}.get(choice)
    if not mode:
        print("未选择有效模式，未修改配置。")
        return 1
    write_config(mode)
    print(f"已保存 LLM 模式：{mode}")
    if mode != "ollama":
        return 0
    status = ollama_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    if not status["installed"]:
        print("请先从 https://ollama.com/download/windows 安装 Ollama，然后重新运行本脚本。")
        return 0
    if not status["service_ready"]:
        print("Ollama 已安装但服务未就绪。请启动 Ollama，再重新运行本脚本。")
        return 0
    if not status["model_ready"]:
        answer = input(f"是否现在下载 {OLLAMA_MODEL}（{OLLAMA_MODEL_SIZE}）？输入 y 确认：").strip().lower()
        if answer == "y":
            return pull_ollama_model()
        print("已跳过下载；Agent 会继续使用规则路由。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure OpsAgent LLM provider")
    parser.add_argument("--mode", choices=["ollama", "openai", "groq", "volcengine", "rules"])
    parser.add_argument("--pull", action="store_true", help="With --mode ollama, explicitly download the recommended model")
    args = parser.parse_args()
    if not args.mode:
        return interactive_setup()
    write_config(args.mode)
    print(f"Configured LLM mode: {args.mode}")
    if args.mode == "ollama":
        print(json.dumps(ollama_status(), ensure_ascii=False, indent=2))
        if args.pull:
            return pull_ollama_model()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

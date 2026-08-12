from pathlib import Path

content = '''import shutil
import subprocess
import os
import re
from typing import Optional, Tuple, Dict, Any
from pathlib import Path
from datetime import datetime

# ===== 配置 =====
MAX_ARG_LENGTH = 128
SESSION_MAX_ENTRIES = 50
WORKSPACE_ROOT = Path(__file__).resolve().parent
SAFE_SERVICE_NAMES = {
    "nginx",
    "mysql",
    "redis",
    "docker",
    "ssh",
    "postgresql",
    "mongodb",
    "httpd",
}
TOOL_META = {
    "check_cpu": {"risk": "low"},
    "check_memory": {"risk": "low"},
    "check_disk": {"risk": "low"},
    "check_service": {"risk": "low"},
    "restart_service": {"risk": "high"},
    "execute_shell": {"risk": "high"},
}
DANGEROUS_TOOLS = {"restart_service", "execute_shell"}
SESSION_HISTORY: list[Dict[str, Any]] = []
SEARCH_EXTENSIONS = {".py", ".txt", ".md", ".log", ".conf", ".ini", ".json"}


def log_session_entry(question: str, task: dict, result: dict) -> dict:
    """记录会话历史，用于后续 Session/Memory 支持。"""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "question": question,
        "task": task,
        "result": result,
    }
    SESSION_HISTORY.append(entry)
    if len(SESSION_HISTORY) > SESSION_MAX_ENTRIES:
        SESSION_HISTORY.pop(0)
    return entry


def get_session_summary(last_n: int = 5) -> str:
    """返回最近 N 条会话历史摘要。"""
    history = SESSION_HISTORY[-last_n:]
    if not history:
        return "当前会话历史为空。"
    lines = []
    for item in history:
        lines.append(
            f"[{item['timestamp']}] {item['question']} -> {item['task']['tool']} => {item['result']}"
        )
    return "\n".join(lines)


def is_safe_text(value: str) -> bool:
    """检查文本参数是否在长度和字符范围内。"""
    return isinstance(value, str) and len(value) <= MAX_ARG_LENGTH and bool(
        re.match(r"^[A-Za-z0-9_\-./: \\]+$", value)
    )


def sanitize_disk_path(path: str) -> Optional[str]:
    """验证磁盘路径是否安全，并返回标准化路径。"""
    if not isinstance(path, str) or len(path) > MAX_ARG_LENGTH:
        return None
    try:
        normalized = Path(path).expanduser().resolve()
    except Exception:
        return None
    if not normalized.exists():
        return None
    if os.name == "nt":
        anchor = normalized.anchor.upper()
        if anchor not in [d.upper() for d in get_available_windows_drives()]:
            return None
    return str(normalized)


def sanitize_service_name(service_name: str) -> Optional[str]:
    """验证服务名称是否合法，并返回小写名称。"""
    if not isinstance(service_name, str) or len(service_name) > 64:
        return None
    normalized = service_name.strip().lower()
    if not re.match(r"^[a-z0-9_\-]+$", normalized):
        return None
    return normalized


def get_available_windows_drives() -> list[str]:
    """列出当前 Windows 主机上可访问的驱动器盘符。"""
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        path = f"{letter}:\\"
        if Path(path).exists():
            drives.append(path)
    return drives


def extract_service_name(question: str) -> Optional[str]:
    """从问题中提取服务名称。"""
    q = question.lower()
    match = re.search(r"(?:服务|service)[:：]?\s*([a-zA-Z0-9_\-]+)", q)
    if match:
        return match.group(1)
    for candidate in SAFE_SERVICE_NAMES:
        if candidate in q:
            return candidate
    return None


def parse_action_and_object(question: str) -> Tuple[Optional[str], Optional[str]]:
    """从自然语言问题中提取动作和对象。"""
    q = question.lower()
    action = None
    if any(word in q for word in ["检查", "查看", "查询", "检测", "看", "inspect", "check"]):
        action = "check"
    elif any(word in q for word in ["重启", "restart", "启动", "stop", "停止"]):
        action = "control"

    object_name = None
    if "cpu" in q or "处理器" in q:
        object_name = "cpu"
    elif "内存" in q or "memory" in q:
        object_name = "memory"
    elif "磁盘" in q or "disk" in q or "df" in q:
        object_name = "disk"
    elif "服务" in q or "service" in q or "nginx" in q:
        object_name = "service"
    return action, object_name


def route_task(question: str) -> dict:
    """将用户问题映射到具体工具调用。"""
    action, object_name = parse_action_and_object(question)
    if action is None or object_name is None:
        return {"tool": "none", "message": "无法识别请求类型", "args": {}}

    if action != "check":
        return {"tool": "none", "message": "目前仅支持查询类型操作", "args": {}}

    if object_name == "cpu":
        return {"tool": "check_cpu", "args": {"action": action, "object": object_name}}
    if object_name == "memory":
        return {"tool": "check_memory", "args": {"action": action, "object": object_name}}
    if object_name == "disk":
        return {"tool": "check_disk", "args": {"path": "/", "action": action, "object": object_name}}
    if object_name == "service":
        service_name = extract_service_name(question) or "nginx"
        return {
            "tool": "check_service",
            "args": {"service_name": service_name, "action": action, "object": object_name},
        }

    return {"tool": "none", "message": "没有匹配到工具", "args": {}}


def validate_and_sanitize_args(tool_name: str, args: dict) -> Tuple[bool, str, dict]:
    """验证工具参数，并返回是否通过、错误信息和清理后的参数。"""
    if not isinstance(args, dict):
        return False, "args 必须是字典", {}

    if tool_name == "check_disk":
        path = args.get("path", "/")
        safe_path = sanitize_disk_path(path)
        if safe_path is None:
            return False, f"非法或不可访问的磁盘路径: {path}", {}
        return True, "", {"path": safe_path, "action": args.get("action"), "object": args.get("object")}

    if tool_name == "check_service":
        service_name = args.get("service_name", "nginx")
        safe_name = sanitize_service_name(service_name)
        if safe_name is None:
            return False, f"非法服务名称: {service_name}", {}
        if safe_name not in SAFE_SERVICE_NAMES:
            return False, f"服务名称不在白名单中: {safe_name}", {}
        return True, "", {"service_name": safe_name, "action": args.get("action"), "object": args.get("object")}

    if tool_name in {"check_cpu", "check_memory"}:
        return True, "", {"action": args.get("action"), "object": args.get("object")}

    return False, "不支持的工具", {}


def approve_tool_call(tool_name: str, args: dict) -> bool:
    """审批工具调用，高风险工具必须额外审批。"""
    if tool_name in DANGEROUS_TOOLS:
        print(f"审批中：{tool_name}({args})")
        return False
    return True


def safe_execute(tool_name: str, args: dict) -> dict:
    """安全执行工具调用。"""
    if not approve_tool_call(tool_name, args):
        return {"status": "blocked", "reason": "waiting approval"}
    func = TOOL_FUNCS.get(tool_name)
    if not func:
        return {"status": "unsupported_tool", "tool": tool_name}
    return func(**args)


def handle_user_query(question: str):
    """处理用户查询，完成路由、参数校验、执行和会话记录。"""
    task = route_task(question)
    tool_name = task.get("tool")
    if tool_name == "none":
        result = {"status": "no_tool", "message": task.get("message")}
        log_session_entry(question, task, result)
        return result

    valid, error, sanitized_args = validate_and_sanitize_args(tool_name, task.get("args", {}))
    if not valid:
        result = {"status": "invalid_args", "error": error}
        log_session_entry(question, task, result)
        return result

    result = safe_execute(tool_name, sanitized_args)
    log_session_entry(question, {"tool": tool_name, "args": sanitized_args}, result)
    return result


def run_file_search(query: str, search_root: Path = WORKSPACE_ROOT) -> dict:
    """在工作区内按文件名或内容搜索匹配项。"""
    if not is_safe_text(query):
        return {"status": "invalid_query", "error": "搜索关键词包含不安全字符或太长。"}
    matches = []
    for file_path in search_root.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix not in SEARCH_EXTENSIONS:
            continue
        name = file_path.name.lower()
        if query.lower() in name:
            matches.append({"path": str(file_path), "match": "filename"})
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore").lower()
            if query.lower() in text:
                matches.append({"path": str(file_path), "match": "content"})
        except OSError:
            continue
    return {"status": "ok", "matches": matches}


TOOL_FUNCS = {
    "check_cpu": check_cpu,
    "check_memory": check_memory,
    "check_disk": check_disk,
    "check_service": check_service,
    "search_files": run_file_search,
}


def handle_search_query(question: str):
    query = question.strip()
    return run_file_search(query)


if __name__ == "__main__":
    print("当前系统支持：CPU、内存、磁盘、nginx 服务查询，以及工作区文件搜索。安全策略会阻止高风险工具。")
    print("示例：帮我检查 CPU, 帮我检查内存, 帮我检查磁盘, 帮我看看 nginx 服务状态, 搜索 agent 文件")
    question = input("请输入查询内容：")
    if question.lower().startswith("搜索") or question.lower().startswith("search"):
        print(handle_search_query(question.replace("搜索", "").strip()))
    else:
        print(handle_user_query(question))
'''
Path('agent.py').write_text(content, encoding='utf-8')

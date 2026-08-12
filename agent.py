import os
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

import memory

MAX_ARG_LENGTH = 128
SAFE_SERVICE_NAMES = {'nginx', 'mysql', 'redis', 'docker', 'ssh', 'postgresql', 'mongodb', 'httpd'}
SEARCH_EXTENSIONS = {'.py', '.txt', '.md', '.log', '.conf', '.ini', '.json'}
DANGEROUS_TOOLS = {'restart_service', 'execute_shell'}
WORKSPACE_ROOT = Path(__file__).resolve().parent


def is_safe_text(value: str) -> bool:
    return isinstance(value, str) and len(value) <= MAX_ARG_LENGTH and bool(re.match(r'^[A-Za-z0-9_\-./: \\]+$', value))


def sanitize_disk_path(path: str) -> Optional[str]:
    if not isinstance(path, str) or len(path) > MAX_ARG_LENGTH:
        return None
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return None
    if not p.exists():
        return None
    if os.name == 'nt' and p.anchor.upper() not in [d.upper() for d in get_available_windows_drives()]:
        return None
    return str(p)


def sanitize_service_name(name: str) -> Optional[str]:
    if not isinstance(name, str) or len(name) > 64:
        return None
    normalized = name.strip().lower()
    return normalized if re.match(r'^[a-z0-9_\-]+$', normalized) else None


def get_available_windows_drives() -> list[str]:
    drives = []
    for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        root = f'{letter}:\\'
        if Path(root).exists():
            drives.append(root)
    return drives


def extract_service_name(question: str) -> Optional[str]:
    q = question.lower()
    m = re.search(r'(?:服务|service)[:：]?\s*([a-z0-9_\-]+)', q)
    if m:
        return m.group(1)
    for svc in SAFE_SERVICE_NAMES:
        if svc in q:
            return svc
    return None


def check_cpu() -> dict:
    if os.name == 'nt':
        try:
            p = subprocess.run(['wmic', 'cpu', 'get', 'loadpercentage', '/value'], capture_output=True, text=True)
            out = p.stdout or ''
            m = re.search(r'LoadPercentage=(\d+)', out)
            return {'cpu_usage_percent': float(m.group(1))} if m else {'error': out.strip()}
        except FileNotFoundError:
            return {'error': 'wmic 未找到'}
    try:
        vals = [int(v) for v in Path('/proc/stat').read_text().split()[1:6]]
        busy = sum(vals[:3])
        return {'cpu_usage_percent': round(100.0 * busy / sum(vals), 2)}
    except Exception as e:
        return {'error': str(e)}


def check_memory() -> dict:
    if os.name == 'nt':
        try:
            p = subprocess.run(['wmic', 'OS', 'get', 'FreePhysicalMemory,TotalVisibleMemorySize', '/value'], capture_output=True, text=True)
            out = p.stdout or ''
            total = re.search(r'TotalVisibleMemorySize=(\d+)', out)
            free = re.search(r'FreePhysicalMemory=(\d+)', out)
            if total and free:
                total_mb = int(total.group(1)) / 1024
                free_mb = int(free.group(1)) / 1024
                return {'total_mb': round(total_mb, 2), 'used_mb': round(total_mb - free_mb, 2), 'available_mb': round(free_mb, 2)}
            return {'error': out.strip()}
        except FileNotFoundError:
            return {'error': 'wmic 未找到'}
    try:
        text = Path('/proc/meminfo').read_text(encoding='utf-8')
        total = int(re.search(r'MemTotal:\s+(\d+)', text).group(1))
        avail = int(re.search(r'MemAvailable:\s+(\d+)', text).group(1))
        return {'total_mb': round(total / 1024, 2), 'used_mb': round((total - avail) / 1024, 2), 'available_mb': round(avail / 1024, 2)}
    except Exception as e:
        return {'error': str(e)}


def check_disk(path: str = '/') -> dict:
    total, used, free = shutil.disk_usage(path)
    return {'path': path, 'total_gb': round(total / 2**30, 2), 'used_gb': round(used / 2**30, 2), 'free_gb': round(free / 2**30, 2)}


def check_service(service_name: str) -> dict:
    try:
        if os.name == 'nt':
            p = subprocess.run(['sc', 'query', service_name], capture_output=True, text=True)
            combined = (p.stdout or '') + '\n' + (p.stderr or '')
            if '1060' in combined or 'service does not exist' in combined.lower():
                return {'status': 'not_found', 'raw': combined}
            m = re.search(r'STATE\s*:\s*\d+\s+(\w+)', combined)
            state = m.group(1).lower() if m else 'unknown'
            return {'status': 'active' if state == 'running' else 'inactive' if state in {'stopped', 'inactive'} else state, 'raw': combined}
        if shutil.which('systemctl') is None:
            return {'error': 'systemctl 未找到'}
        p = subprocess.run(['systemctl', 'is-active', service_name], capture_output=True, text=True)
        status = (p.stdout or p.stderr or '').strip()
        return {'status': status or 'inactive', 'raw': status}
    except FileNotFoundError as e:
        return {'error': str(e)}


def search_files(query: str) -> dict:
    if not is_safe_text(query):
        return {'status': 'invalid_query', 'error': '查询不安全'}
    q = query.lower()
    matches = []
    for fp in WORKSPACE_ROOT.rglob('*'):
        if not fp.is_file() or fp.suffix not in SEARCH_EXTENSIONS:
            continue
        if q in fp.name.lower():
            matches.append({'path': str(fp), 'match': 'filename'})
            continue
        try:
            text = fp.read_text(encoding='utf-8', errors='ignore').lower()
            if q in text:
                matches.append({'path': str(fp), 'match': 'content'})
        except OSError:
            continue
    return {'status': 'ok', 'matches': matches}


def parse_action_and_object(question: str) -> Tuple[Optional[str], Optional[str]]:
    q = question.lower()
    action = 'check' if any(w in q for w in ['检查', '查看', '查询', '检测', 'check', 'inspect']) else 'control' if any(w in q for w in ['重启', 'restart', '启动', '停止', 'stop']) else None
    if 'cpu' in q or '处理器' in q:
        obj = 'cpu'
    elif '内存' in q or 'memory' in q:
        obj = 'memory'
    elif '磁盘' in q or 'disk' in q or 'df' in q:
        obj = 'disk'
    elif '服务' in q or 'service' in q or 'nginx' in q:
        obj = 'service'
    elif '搜索' in q or 'search' in q:
        obj = 'search'
    elif any(w in q for w in ['记忆', '回顾', '历史', '上次', '之前', 'summary', '总结']):
        obj = 'memory_request'
    else:
        obj = None
    return action, obj


def query_memory(query: str) -> dict:
    result = memory.search_memory(query, max_entries=10)
    return {'status': 'ok', 'memory': result}


def route_task(question: str) -> dict:
    action, obj = parse_action_and_object(question)
    if obj == 'memory_request':
        return {'tool': 'query_memory', 'args': {'query': question}}
    if obj == 'search':
        return {'tool': 'search_files', 'args': {'query': question}}
    if action != 'check':
        return {'tool': 'none', 'message': '当前仅支持查询类型操作', 'args': {}}
    if obj == 'cpu':
        return {'tool': 'check_cpu', 'args': {}}
    if obj == 'memory':
        return {'tool': 'check_memory', 'args': {}}
    if obj == 'disk':
        return {'tool': 'check_disk', 'args': {'path': '/'}}
    if obj == 'service':
        return {'tool': 'check_service', 'args': {'service_name': extract_service_name(question) or 'nginx'}}
    return {'tool': 'none', 'message': '没有匹配到工具', 'args': {}}


def validate_args(tool_name: str, args: dict) -> Tuple[bool, str, dict]:
    if tool_name == 'check_disk':
        safe_path = sanitize_disk_path(args.get('path', '/'))
        return (True, '', {'path': safe_path}) if safe_path else (False, '非法或不可访问的磁盘路径', {})
    if tool_name == 'check_service':
        safe_name = sanitize_service_name(args.get('service_name', 'nginx'))
        if not safe_name or safe_name not in SAFE_SERVICE_NAMES:
            return False, f'服务名称不安全或不在白名单: {args.get("service_name")}', {}
        return True, '', {'service_name': safe_name}
    if tool_name == 'search_files':
        query = args.get('query', '')
        return (True, '', {'query': query}) if is_safe_text(query) else (False, '搜索关键词不安全', {})
    if tool_name == 'query_memory':
        query = args.get('query', '')
        return (True, '', {'query': query}) if is_safe_text(query) else (False, '记忆查询关键词不安全', {})
    if tool_name in {'check_cpu', 'check_memory'}:
        return True, '', {}
    return False, '不支持的工具', {}


def approve_tool_call(tool_name: str, args: dict) -> bool:
    return tool_name not in DANGEROUS_TOOLS


def safe_execute(tool_name: str, args: dict) -> dict:
    if not approve_tool_call(tool_name, args):
        return {'status': 'blocked', 'reason': '危险操作需要审批'}
    func = TOOL_FUNCS.get(tool_name)
    return func(**args) if func else {'status': 'unsupported_tool'}


def handle_user_query(question: str) -> dict:
    task = route_task(question)
    if task['tool'] == 'none':
        result = {'status': 'no_tool', 'message': task['message']}
        memory.log_session_entry(question, task, result)
        return result
    ok, err, clean_args = validate_args(task['tool'], task['args'])
    if not ok:
        result = {'status': 'invalid_args', 'error': err}
        memory.log_session_entry(question, task, result)
        return result
    result = safe_execute(task['tool'], clean_args)
    memory.log_session_entry(question, task, result)
    return result


TOOL_FUNCS = {
    'check_cpu': check_cpu,
    'check_memory': check_memory,
    'check_disk': check_disk,
    'check_service': check_service,
    'search_files': search_files,
    'query_memory': query_memory,
}


if __name__ == '__main__':
    print('本地运维代理已启动，当前仅支持低风险查询。')
    print('示例：检查 CPU、检查内存、检查磁盘、检查 nginx 服务、搜索 文件名/内容')
    q = input('请输入指令：')
    print(handle_user_query(q))

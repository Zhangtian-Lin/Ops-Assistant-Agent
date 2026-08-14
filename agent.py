import os
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from core import memory

MAX_ARG_LENGTH = 128
SAFE_SERVICE_NAMES = {'nginx', 'mysql', 'redis', 'docker', 'ssh', 'postgresql', 'mongodb', 'httpd'}
SEARCH_EXTENSIONS = {'.py', '.txt', '.md', '.log', '.conf', '.ini', '.json'}
DANGEROUS_TOOLS = {'restart_service', 'execute_shell'}
WORKSPACE_ROOT = Path(__file__).resolve().parent


def is_safe_text(value: str) -> bool:
    if not isinstance(value, str) or len(value) > MAX_ARG_LENGTH:
        return False
    # 允许中英文、数字、常见标点与空白；拒绝控制字符（防注入），不再强制 ASCII
    return bool(re.match(r'^[\w\u4e00-\u9fff\s.,;:!?()\-_/\\"\'+=\[\]{}@#$%^&*]+$', value, re.UNICODE))


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
            p = subprocess.run(['wmic', 'cpu', 'get', 'loadpercentage', '/value'], capture_output=True, text=True, encoding='gbk', errors='ignore')
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
            p = subprocess.run(['wmic', 'OS', 'get', 'FreePhysicalMemory,TotalVisibleMemorySize', '/value'], capture_output=True, text=True, encoding='gbk', errors='ignore')
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


def analyze_disk_distribution(path: str = '/') -> dict:
    """只扫描根目录，统计其下一级文件和文件夹的大小，隔离的新功能。"""
    if not os.path.exists(path):
        return {'error': '路径不存在'}

    distribution = []
    try:
        # 只扫描最外层（根目录）
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    size = entry.stat().st_size
                    distribution.append({'name': entry.name, 'type': 'file', 'size_mb': round(size / (1024*1024), 2)})
                elif entry.is_dir(follow_symlinks=False):
                    # 因为只扫描根目录，为了防止 C 盘深层遍历太慢，这里仅作标识，或可选用快查
                    # 这里遵照用户"只扫描根目录"的指令，仅列出第一层文件夹，不进行深度遍历求总大小。
                    distribution.append({'name': entry.name, 'type': 'directory', 'size_mb': 'unknown_without_deep_scan'})
            except Exception:
                continue
    except PermissionError:
        return {'error': '无权限扫描该路径'}

    return {'path': path, 'items': distribution}


def check_service(service_name: str) -> dict:
    try:
        if os.name == 'nt':
            p = subprocess.run(['sc', 'query', service_name], capture_output=True, text=True, encoding='gbk', errors='ignore')
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


def audit_skill(path: str) -> dict:
    """调用集成的安全扫描器审计目标 Skill 路径。"""
    try:
        from core.security_scanner.scan_engine import scan_skill
    except ImportError:
        return {'status': 'error', 'error': '安全扫描模块未正确导入'}

    if not os.path.exists(path):
        return {'status': 'error', 'error': f'目标路径不存在: {path}'}

    try:
        result = scan_skill(path)
        findings_summary = []
        for f in result.findings:
            findings_summary.append({
                'rule': f.rule_name,
                'severity': f.severity,
                'location': f.location,
                'desc': f.description,
                'remediation': f.remediation
            })
        return {
            'skill_name': result.skill.name,
            'verdict': result.verdict,
            'max_severity': result.max_severity,
            'summary': result.summary,
            'findings': findings_summary
        }
    except Exception as e:
        return {'status': 'error', 'error': f'扫描失败: {str(e)}'}


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
    action = 'check' if any(w in q for w in ['查', '查看', '查询', '检测', '看', 'check', 'inspect', '分布', '详情', '占用']) else 'control' if any(w in q for w in ['重启', 'restart', '启动', '停止', 'stop']) else None
    # 先判断“明确意图词”（记忆/搜索/知识库/审计），避免被宽泛实体词（如“服务器”含“服务”）误抢
    if any(w in q for w in ['记忆', '回顾', '历史', '上次', '之前', 'summary', '总结']):
        # detect clear/reset requests explicitly
        if any(cw in q for cw in ['清空', '清除', '删除', '重置', 'reset']):
            obj = 'memory_clear'
        else:
            obj = 'memory_request'
    elif '搜索' in q or 'search' in q:
        obj = 'search'
    elif any(w in q for w in ['标准', '规范', 'sop', '手册', '排查', '最佳实践', '怎么处理', '如何解决', '怎么解决', '如何排查']):
        obj = 'knowledge'
    elif any(w in q for w in ['安全', '扫描', '审计', 'scan', 'audit', 'security']):
        obj = 'audit'
    elif any(w in q for w in ['审批', '待批准', '待处理', 'pending']):
        obj = 'list_approvals'
    elif any(w in q for w in ['批准', '同意', 'approve']):
        obj = 'approve'
    # 再判断对象实体
    elif 'cpu' in q or '处理器' in q:
        obj = 'cpu'
    elif '内存' in q or 'memory' in q:
        obj = 'memory'
    elif any(w in q for w in ['分布', '详情', '占用']) and ('盘' in q or 'disk' in q or '磁盘' in q):
        obj = 'disk_distribution'
    elif '磁盘' in q or 'disk' in q or 'df' in q or '盘' in q:
        obj = 'disk'
    elif '服务' in q or 'service' in q or 'nginx' in q:
        obj = 'service'
    else:
        obj = None
    return action, obj


def query_memory(query: str) -> dict:
    result = memory.search_memory(query, max_entries=10)
    # 一个 query 同时打两库：个人记忆 + 静态知识库，来源分别标注
    knowledge = memory.retrieve_knowledge(query, top_k=5)
    return {
        'status': 'ok',
        'source': 'memory',
        'memory': result,
        'knowledge_matches': knowledge,
    }


def query_knowledge(query: str) -> dict:
    matches = memory.retrieve_knowledge(query, top_k=5)
    return {'status': 'ok', 'source': 'knowledge', 'knowledge_matches': matches}


def clear_memory() -> dict:
    # create a pending approval to clear memory
    req = memory.request_clear_session_history(requester='agent')
    return {'status': 'pending_approval', 'request_id': req.get('request_id')}


def list_approvals() -> dict:
    all_reqs = memory.list_pending_approvals()
    pending = [p for p in all_reqs if p.get('status') == 'pending']
    return {'status': 'ok', 'pending': pending, 'pending_count': len(pending)}


def _execute_clear_session_history(details: dict) -> dict:
    return memory.perform_clear_session_history()


# 审批动作 → 执行函数（批准后真正执行什么）。执行函数统一签名 func(details) -> dict
APPROVAL_EXECUTORS = {
    'clear_session_history': _execute_clear_session_history,
    # 以后加动作，就往这里加一行，例如：
    # 'restart_service': _execute_restart_service,
}


def approve_request_tool(request_id: str) -> dict:
    result = memory.approve_request(request_id, approver='user')
    if result.get('status') != 'approved':
        return {'status': 'ok', 'request_id': request_id, 'approval': result}

    action = result['action']
    executor = APPROVAL_EXECUTORS.get(action)
    if executor is None:
        return {'status': 'ok', 'request_id': request_id,
                'approval': {'status': 'unknown_action', 'action': action}}

    exec_result = executor(result.get('details', {}))
    return {'status': 'ok', 'request_id': request_id, 'approval': exec_result}


def route_task(question: str) -> dict:
    from core import intent_parser
    intent = intent_parser.parse_intent(question, parse_action_and_object)
    action, obj = intent['action'], intent['object']
    llm_args = intent.get('args') or {}
    # 安全审计是只读操作，即使请求中没有“检查”等关键词也应允许路由。
    if obj == 'audit':
        action = 'check'
    if obj == 'memory_request':
        return {'tool': 'query_memory', 'args': {'query': llm_args.get('query') or question}}
    if obj == 'memory_clear':
        return {'tool': 'clear_memory', 'args': {}}
    if obj == 'search':
        return {'tool': 'search_files', 'args': {'query': llm_args.get('query') or question}}
    if obj == 'knowledge':
        return {'tool': 'query_knowledge', 'args': {'query': llm_args.get('query') or question}}
    if obj == 'list_approvals':
        return {'tool': 'list_approvals', 'args': {}}
    if obj == 'approve':
        m = re.search(r'(apr-[A-Za-z0-9]+)', question)
        request_id = llm_args.get('request_id') or (m.group(1) if m else '')
        return {'tool': 'approve_request_tool', 'args': {'request_id': request_id}}
    if action != 'check':
        return {'tool': 'none', 'message': '当前仅支持查询类型操作', 'args': {}}
    if obj == 'cpu':
        return {'tool': 'check_cpu', 'args': {}}
    if obj == 'memory':
        return {'tool': 'check_memory', 'args': {}}
    if obj == 'disk_distribution':
        m = re.search(r'([a-zA-Z])\s*盘', question.lower())
        path_arg = llm_args.get('path') or (f"{m.group(1).upper()}:\\" if m else '/')
        return {'tool': 'analyze_disk_distribution', 'args': {'path': path_arg}}
    if obj == 'disk':
        m = re.search(r'([a-zA-Z])\s*盘', question.lower())
        path_arg = llm_args.get('path') or (f"{m.group(1).upper()}:\\" if m else '/')
        return {'tool': 'check_disk', 'args': {'path': path_arg}}
    if obj == 'service':
        service_name = llm_args.get('service_name') or extract_service_name(question) or 'nginx'
        return {'tool': 'check_service', 'args': {'service_name': service_name}}
    if obj == 'audit':
        m = re.search(r'["\']([^"\']+)["\']', question)
        # 支持从整句提取路径模式，若有盘符等
        if not m:
            m = re.search(r'([a-zA-Z]:\\[a-zA-Z0-9_\-\\. ]+)', question)
        path_arg = llm_args.get('path') or (m.group(1) if m else '.')
        return {'tool': 'audit_skill', 'args': {'path': path_arg}}
    return {'tool': 'none', 'message': '没有匹配到工具', 'args': {}}


def validate_args(tool_name: str, args: dict) -> Tuple[bool, str, dict]:
    if tool_name in {'check_disk', 'analyze_disk_distribution', 'audit_skill'}:
        safe_path = sanitize_disk_path(args.get('path', '/'))
        return (True, '', {'path': safe_path}) if safe_path else (False, '非法或不可访问的路径', {})
    if tool_name == 'check_service':
        safe_name = sanitize_service_name(args.get('service_name', 'nginx'))
        if not safe_name or safe_name not in SAFE_SERVICE_NAMES:
            return False, f'服务名称不安全或不在白名单: {args.get("service_name")}', {}
        return True, '', {'service_name': safe_name}
    if tool_name == 'search_files':
        query = args.get('query', '')
        return (True, '', {'query': query}) if is_safe_text(query) else (False, '搜索关键词不安全', {})
    if tool_name in {'query_memory', 'query_knowledge'}:
        query = args.get('query', '')
        return (True, '', {'query': query}) if is_safe_text(query) else (False, '查询关键词不安全', {})
    if tool_name == 'clear_memory':
        return True, '', {}
    if tool_name == 'list_approvals':
        return True, '', {}
    if tool_name == 'approve_request_tool':
        request_id = args.get('request_id', '')
        if re.match(r'^apr-[A-Za-z0-9]+$', request_id):
            return True, '', {'request_id': request_id}
        return False, '非法的审批请求 ID', {}
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
    'analyze_disk_distribution': analyze_disk_distribution,
    'check_service': check_service,
    'audit_skill': audit_skill,
    'search_files': search_files,
    'query_memory': query_memory,
    'query_knowledge': query_knowledge,
    'clear_memory': clear_memory,
    'list_approvals': list_approvals,
    'approve_request_tool': approve_request_tool,
}


def check_pending_approvals() -> None:
    """检查是否有待审批请求，若有则主动提示。"""
    pending = memory.list_pending_approvals()
    active = [p for p in pending if p.get('status') == 'pending']
    if active:
        print(f'\n⚠️ 有 {len(active)} 条待审批请求待处理：')
        for p in active:
            print(f"  - {p.get('request_id')}  ({p.get('action')})")


def safe_input(prompt_text: str) -> str:
    """解决 Windows 内嵌终端下 Python 原生 input() 无法输入中文的兼容性读取器。"""
    print(prompt_text, end='', flush=True)
    try:
        line = sys.stdin.readline()
        if not line:
            return ''
        return line.strip()
    except Exception:
        return input(prompt_text).strip()


if __name__ == '__main__':
    import sys
    import io
    # 强制重定向 Windows 控制台标准输入输出编码为 utf-8
    if sys.platform == 'win32':
        try:
            sys.stdin.reconfigure(encoding='utf-8')
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    # 支持命令行直接传参测试，例如: python agent.py "帮我检查CPU"
    if len(sys.argv) > 1:
        query_text = ' '.join(sys.argv[1:])
        print(f"执行命令行参数指令: {query_text}")
        print("回应：", handle_user_query(query_text))
        sys.exit(0)

    print('===========================================================')
    print('本地运维代理已启动，当前支持低风险查询与 BAAI 深度向量记忆。')
    print('示例：检查 CPU、检查内存、检查磁盘、检查 nginx 服务、回顾一下之前网页服务器的情况')
    print('输入 exit 退出程序')
    print('===========================================================')
    check_pending_approvals()
    try:
        while True:
            q = safe_input('\n请输入指令：')
            if not q:
                continue
            if q.lower() in {'exit', 'quit', '退出'}:
                print('系统已退出。')
                break
            res = handle_user_query(q)
            print('回应：', res)
            check_pending_approvals()
    except (KeyboardInterrupt, EOFError):
        print('\n系统已退出。')

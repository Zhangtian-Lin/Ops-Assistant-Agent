import os
import re
import shutil
import subprocess
import getpass
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from core import memory
from core.broker import BrokerClient
from core.identity import get_current_principal
from core.network import check_dns, check_local_state, check_tcp, check_tls
from core.security_mode import build_context, permissions_for
from core.tools.catalog import build_tool_registry
from core.tools.executor import ToolExecutor
from core.tools.models import ToolRequest
from core.windows_checks import CHECKS as WINDOWS_CHECKS, run_check as run_windows_check

MAX_ARG_LENGTH = 128
SAFE_SERVICE_NAMES = {'nginx', 'mysql', 'redis', 'docker', 'ssh', 'postgresql', 'mongodb', 'httpd'}
SEARCH_EXTENSIONS = {'.py', '.txt', '.md', '.log', '.conf', '.ini', '.json'}
WORKSPACE_ROOT = Path(__file__).resolve().parent

SYSTEM_CHECK_KEYWORDS = (
    ('gpu', ('gpu', '\u663e\u5361', '\u663e\u5b58')),
    ('disk_health', ('smart', '\u786c\u76d8\u5065\u5eb7', '\u78c1\u76d8\u5065\u5eb7', '\u574f\u6247\u533a', '\u78c1\u76d8\u98ce\u9669', '\u786c\u76d8\u98ce\u9669')),
    ('processes', ('process', '\u8fdb\u7a0b')),
    ('system_inventory', ('\u51e0\u4e2a\u7cfb\u7edf', '\u64cd\u4f5c\u7cfb\u7edf', '\u542f\u52a8\u9879', 'windows version')),
    ('security_baseline', ('defender', '\u9632\u706b\u5899', '\u5b89\u5168\u57fa\u7ebf', 'windows update', '\u8865\u4e01')),
    ('event_errors', ('event log', '\u4e8b\u4ef6\u65e5\u5fd7', '\u7cfb\u7edf\u65e5\u5fd7', '\u9519\u8bef\u65e5\u5fd7')),
    ('driver_issues', ('driver', '\u9a71\u52a8\u5f02\u5e38', '\u9a71\u52a8\u7a0b\u5e8f')),
    ('scheduled_tasks', ('scheduled task', '\u8ba1\u5212\u4efb\u52a1')),
    ('user_sessions', ('query user', '\u7528\u6237\u4f1a\u8bdd', '\u5df2\u767b\u5f55\u7528\u6237')),
    ('power', ('battery', '\u7535\u6c60', '\u7535\u6e90\u8ba1\u5212')),
)


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
    # Treat attempts to override policy or request arbitrary command execution as untrusted text,
    # never as an instruction to a memory/search tool.
    if any(phrase in q for phrase in ('忽略之前规则', '忽略所有规则', 'ignore previous rules', 'ignore all rules', '执行 powershell', '运行任意命令', 'arbitrary command')):
        return None, None
    performance_question = any(w in q for w in ['电脑卡', '系统卡', '运行慢', '响应慢', '响应有点慢', '有点卡', '变卡', '这么卡', '卡顿', '越来越慢', '特别慢', '反应慢', '有延迟', 'lag', 'slow'])
    diagnostic_question = performance_question or any(w in q for w in ['是不是', '好像', '感觉', '不够用', '紧张', '快爆', '塞满', '没空间', '危险', '断网', '不稳定', '出问题'])
    action = 'check' if diagnostic_question or any(w in q for w in ['查', '查看', '查询', '检测', '看', 'check', 'inspect', '分布', '详情', '占用']) else 'control' if any(w in q for w in ['重启', 'restart', '启动', '停止', 'stop']) else None
    # 先判断“明确意图词”（记忆/搜索/知识库/审计），避免被宽泛实体词（如“服务器”含“服务”）误抢
    if any(w in q for w in ['记忆', '回顾', '历史', '上次', '之前', '忘了刚才', 'summary', '总结']) or ('会话' in q and any(w in q for w in ['清', '删', '重置', 'reset'])):
        # detect clear/reset requests explicitly
        if any(cw in q for cw in ['清空', '清除', '删除', '删掉', '删记忆', '重置', 'reset']):
            obj = 'memory_clear'
        else:
            obj = 'memory_request'
    elif '搜索' in q or 'search' in q:
        obj = 'search'
    elif any(w in q for w in ['标准', '规范', 'sop', '手册', '排查', '最佳实践', '怎么处理', '如何解决', '怎么解决', '如何排查']):
        obj = 'knowledge'
    elif any(w in q for w in ['安全', '扫描', '审计', 'scan', 'audit', 'security']):
        obj = 'audit'
    elif any(w in q for w in ['取消审批', '撤销审批', '取消待批', '撤销待批', 'cancel approval']):
        obj = 'cancel'
    elif any(w in q for w in ['审批', '待批准', '待处理', 'pending']):
        obj = 'list_approvals'
    elif any(w in q for w in ['批准', '同意', 'approve']):
        obj = 'approve'
    # 再判断对象实体
    elif performance_question:
        # A deterministic first diagnostic when no LLM is available. It stays read-only.
        obj = 'cpu'
    elif 'cpu' in q or '处理器' in q:
        obj = 'cpu'
    elif '内存' in q or 'memory' in q:
        obj = 'memory'
    elif any(w in q for w in ['分布', '详情', '占用', '占空间', '哪些内容']) and ('盘' in q or 'disk' in q or '磁盘' in q):
        obj = 'disk_distribution'
    elif '磁盘' in q or 'disk' in q or 'df' in q or '盘' in q:
        obj = 'disk'
    elif '服务' in q or 'service' in q or 'nginx' in q:
        obj = 'service'
    elif any(w in q for w in ['network', 'dns', 'tcp', 'tls', '\u7f51\u7edc', '\u7f51\u5361', '\u7aef\u53e3', '\u8bc1\u4e66', '断网', '网好像']):
        obj = 'network'
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


def check_network(query: str) -> dict:
    """Route a read-only network question; all remote targets are policy-gated."""
    lowered = query.lower()
    if not any(word in lowered for word in ('dns', 'tcp', 'tls', 'network', '\u7f51\u7edc', '\u7f51\u5361', '\u7aef\u53e3', '\u8bc1\u4e66')):
        return check_local_state()
    if not any(word in lowered for word in ('dns', 'tcp', 'tls', '\u7aef\u53e3', '\u8bc1\u4e66')):
        return check_local_state()
    target_match = re.search(r'(?<![\w-])((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}|(?:\d{1,3}\.){3}\d{1,3})(?![\w-])', query)
    if not target_match:
        return {'status': 'invalid_request', 'error': 'Remote DNS/TCP/TLS checks require an explicit hostname or IP address.'}
    target = target_match.group(1)
    if 'dns' in lowered:
        return check_dns(target)
    port_match = re.search(r'(?<!\d)([1-9]\d{0,4})(?!\d)', query)
    port = int(port_match.group(1)) if port_match else 443 if 'tls' in lowered or '\u8bc1\u4e66' in lowered else None
    if port is None or port > 65535:
        return {'status': 'invalid_request', 'error': 'TCP checks require a port from 1 to 65535.'}
    return check_tls(target, port) if 'tls' in lowered or '\u8bc1\u4e66' in lowered else check_tcp(target, port)


def system_check_category(question: str) -> Optional[str]:
    lowered = question.lower()
    for category, keywords in SYSTEM_CHECK_KEYWORDS:
        if any(keyword in lowered for keyword in keywords):
            return category
    # Treat a disk-failure/risk question as health rather than a capacity query.
    if ('\u78c1\u76d8' in lowered or 'disk' in lowered) and any(keyword in lowered for keyword in ('\u98ce\u9669', '\u6545\u969c', '\u5065\u5eb7', 'health', 'failure')):
        return 'disk_health'
    return None


def check_system(category: str) -> dict:
    return run_windows_check(category)


def clear_memory() -> dict:
    response = BrokerClient().call('create', action='clear_session_history')
    if not response.get('ok'):
        return {'status': 'broker_unavailable', 'error': response.get('error')}
    request = response['result']['request']
    request_number = _request_number(request['request_id'])
    return {
        'status': 'pending_approval',
        'request_number': request_number,
        'expires_at': request['expires_at'],
        'action': request['action'],
        'next_step': f'输入“批准 {request_number}”执行，或“取消 {request_number}”撤销。',
    }


def _pending_requests() -> list:
    response = BrokerClient().call('list')
    return response.get('requests', []) if response.get('ok') else []


def _request_number(request_id: str) -> Optional[int]:
    """Map a displayed short number to the current pending-request snapshot."""
    for number, request in enumerate(_pending_requests(), start=1):
        if request.get('request_id') == request_id:
            return number
    return None


def _resolve_request_reference(reference: str) -> tuple[str, Optional[int]]:
    """Resolve a full ID or a displayed 1-based number to the broker's real ID."""
    if re.fullmatch(r'apr-[A-Za-z0-9_-]{16,}', reference):
        return reference, _request_number(reference)
    if re.fullmatch(r'[1-9][0-9]*', reference):
        pending = _pending_requests()
        number = int(reference)
        if number <= len(pending):
            return pending[number - 1]['request_id'], number
    return '', None


def list_approvals() -> dict:
    response = BrokerClient().call('list')
    if not response.get('ok'):
        return {'status': 'broker_unavailable', 'error': response.get('error')}
    pending = response.get('requests', [])
    return {
        'status': 'ok',
        'pending': [
            {
                'number': number,
                'action': item.get('action'),
                'expires_at': item.get('expires_at'),
            }
            for number, item in enumerate(pending, start=1)
        ],
        'pending_count': len(pending),
        'hint': '输入“批准 编号”执行，或“取消 编号”撤销。',
    }


def approve_request_tool(request_id: str, confirmation: str = '', request_number: Optional[int] = None) -> dict:
    response = BrokerClient().call('approve', request_id=request_id, confirmation=confirmation)
    if not response.get('ok'):
        return {'status': 'approval_rejected', 'request_number': request_number, 'approval': response}
    return {'status': 'ok', 'request_number': request_number, 'message': '审批已执行。'}


def cancel_request_tool(request_id: str, request_number: Optional[int] = None) -> dict:
    response = BrokerClient().call('cancel', request_id=request_id)
    if not response.get('ok'):
        return {'status': 'cancellation_rejected', 'request_number': request_number, 'cancellation': response}
    return {'status': 'ok', 'request_number': request_number, 'message': '审批请求已取消。'}


def route_task(question: str, capture: Optional[dict] = None) -> dict:
    """Map an input to a registered tool request; capture is observability-only."""
    if _is_multi_step_request(question):
        if capture is not None:
            capture.update({'source': 'multi_step_rejection', 'intent': {'action': None, 'object': None, 'args': {}}})
        return {'tool': 'none', 'message': '当前一次只执行一个操作；请把多个检查或操作拆开输入。', 'args': {}}
    if _is_unsafe_control_request(question):
        if capture is not None:
            capture.update({'source': 'policy_rejection', 'intent': {'action': None, 'object': None, 'args': {}}})
        return {'tool': 'none', 'message': '该控制操作没有已注册且获授权的工具。', 'args': {}}
    category = system_check_category(question)
    knowledge_markers = ('标准', '规范', 'sop', '手册', '排查', '最佳实践', '怎么处理', '如何解决', '怎么解决', '如何排查')
    if category and not any(marker in question.lower() for marker in knowledge_markers):
        if capture is not None:
            capture.update({'source': 'system_rule', 'intent': {'action': 'check', 'object': 'system', 'args': {'category': category}}})
        return {'tool': 'check_system', 'args': {'category': category}}
    from core import intent_parser
    intent = intent_parser.parse_intent(question, parse_action_and_object)
    if capture is not None:
        capture.update({'source': intent.get('source', 'unknown'), 'intent': {'action': intent.get('action'), 'object': intent.get('object'), 'args': intent.get('args') or {}}})
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
    if obj == 'network':
        return {'tool': 'check_network', 'args': {'query': llm_args.get('query') or question}}
    if obj == 'list_approvals':
        return {'tool': 'list_approvals', 'args': {}}
    if obj == 'approve':
        m = re.search(r'(apr-[A-Za-z0-9_-]+)', question)
        number_match = re.search(r'(?<!\d)([1-9]\d*)(?!\d)', question)
        reference = str(llm_args.get('request_id') or (m.group(1) if m else (number_match.group(1) if number_match else '')))
        request_id, request_number = _resolve_request_reference(reference)
        if not request_id:
            return {'tool': 'none', 'message': '找不到该待审批编号；请先输入“查看待审批”。', 'args': {}}
        confirmation = f'APPROVE {request_id}'
        return {'tool': 'approve_request_tool', 'args': {'request_id': request_id, 'confirmation': confirmation, 'request_number': request_number}}
    if obj == 'cancel':
        m = re.search(r'(apr-[A-Za-z0-9_-]+)', question)
        number_match = re.search(r'(?<!\d)([1-9]\d*)(?!\d)', question)
        reference = str(llm_args.get('request_id') or (m.group(1) if m else (number_match.group(1) if number_match else '')))
        request_id, request_number = _resolve_request_reference(reference)
        if not request_id:
            return {'tool': 'none', 'message': '找不到该待审批编号；请先输入“查看待审批”。', 'args': {}}
        return {'tool': 'cancel_request_tool', 'args': {'request_id': request_id, 'request_number': request_number}}
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


def _is_unsafe_control_request(question: str) -> bool:
    lowered = question.lower()
    markers = ('关闭防火墙', '禁用 defender', '格式化', '创建管理员', '导出所有密码', '导出密码', '修改系统注册表', '停止所有服务', '上传用户目录', '删除所有日志')
    return any(marker in lowered for marker in markers)


def _is_multi_step_request(question: str) -> bool:
    lowered = question.lower()
    if not any(marker in lowered for marker in ('和', '并', '然后', ' 再', '再停止', '、', '后批准')):
        return False
    capabilities = set()
    checks = (
        ('cpu', ('cpu', '处理器')),
        ('memory', ('内存', 'memory')),
        ('disk_health', ('磁盘健康', '磁盘故障', 'disk health')),
        ('disk_distribution', ('空间分布', '占用详情', '哪些内容占空间')),
        ('disk', ('盘空间', '磁盘空间')),
        ('network', ('网络', '网卡', '断网', 'network')),
        ('service', ('服务', 'nginx', 'mysql', 'redis')),
        ('audit', ('扫描', '审计')),
        ('search', ('搜索', 'search')),
        ('memory_read', ('回顾', '历史')),
        ('memory_clear', ('清空记忆', '删除记忆', '删记忆')),
        ('approval', ('批准', '审批')),
        ('event_errors', ('错误日志', '事件日志')),
        ('driver', ('驱动',)),
        ('gpu', ('gpu', '显卡')),
        ('control', ('停止', '关闭', '禁用')),
    )
    for name, keywords in checks:
        if any(keyword in lowered for keyword in keywords):
            capabilities.add(name)
    # A specific disk subtype supersedes the generic disk mention within the same clause.
    if 'disk' in capabilities and len(capabilities & {'disk_health', 'disk_distribution'}) == 1:
        capabilities.remove('disk')
    return len(capabilities) >= 2


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
    if tool_name == 'check_network':
        query = args.get('query', '')
        return (True, '', {'query': query}) if is_safe_text(query) else (False, '网络查询参数不安全', {})
    if tool_name == 'check_system':
        category = args.get('category', '')
        return (True, '', {'category': category}) if category in WINDOWS_CHECKS else (False, '不支持的系统检查类别', {})
    if tool_name == 'clear_memory':
        return True, '', {}
    if tool_name == 'list_approvals':
        return True, '', {}
    if tool_name in {'approve_request_tool', 'cancel_request_tool'}:
        request_id = args.get('request_id', '')
        if re.match(r'^apr-[A-Za-z0-9_-]{16,}$', request_id):
            request_number = args.get('request_number')
            if request_number is not None and (not isinstance(request_number, int) or request_number < 1):
                return False, '非法的审批请求编号', {}
            if tool_name == 'approve_request_tool':
                confirmation = args.get('confirmation', '')
                return True, '', {'request_id': request_id, 'confirmation': confirmation if isinstance(confirmation, str) else '', 'request_number': request_number}
            return True, '', {'request_id': request_id, 'request_number': request_number}
        return False, '非法的审批请求 ID', {}
    if tool_name in {'check_cpu', 'check_memory'}:
        return True, '', {}
    return False, '不支持的工具', {}


def _current_permissions() -> tuple[str, ...]:
    """Derive permissions from the authenticated OS identity; fail closed."""
    try:
        return tuple(permissions_for(build_context(get_current_principal())))
    except Exception:
        return ()


def safe_execute(tool_name: str, args: dict, trace_id: Optional[str] = None) -> dict:
    request = ToolRequest(
        tool=tool_name,
        arguments=args,
        actor_permissions=_current_permissions(),
        trace_id=trace_id or f"trace-{uuid.uuid4().hex}",
    )
    return TOOL_EXECUTOR.execute(request).to_dict()


def handle_user_query(question: str) -> dict:
    """Compatibility entry point; the explicit runtime owns each task lifecycle."""
    return AGENT_RUNTIME.handle(question)


_TOOL_HANDLERS = {
    'check_cpu': check_cpu,
    'check_memory': check_memory,
    'check_disk': check_disk,
    'analyze_disk_distribution': analyze_disk_distribution,
    'check_service': check_service,
    'check_network': check_network,
    'check_system': check_system,
    'audit_skill': audit_skill,
    'search_files': search_files,
    'query_memory': query_memory,
    'query_knowledge': query_knowledge,
    'clear_memory': clear_memory,
    'list_approvals': list_approvals,
    'approve_request_tool': approve_request_tool,
    'cancel_request_tool': cancel_request_tool,
}

_TOOL_VALIDATORS = {
    name: (lambda args, tool_name=name: validate_args(tool_name, args))
    for name in _TOOL_HANDLERS
}
TOOL_REGISTRY = build_tool_registry(_TOOL_HANDLERS, _TOOL_VALIDATORS)
TOOL_EXECUTOR = ToolExecutor(TOOL_REGISTRY)

# Runtime is deliberately created after the registry: it orchestrates the existing
# router and executor but cannot bypass either the registry or Broker boundary.
from core.runtime import AgentRuntime

AGENT_RUNTIME = AgentRuntime(
    router=route_task,
    executor=lambda tool, args, trace_id: safe_execute(tool, args, trace_id),
    session_logger=memory.log_session_entry,
)


def check_pending_approvals() -> None:
    """检查是否有待审批请求，若有则主动提示。"""
    response = BrokerClient().call('list')
    active = response.get('requests', []) if response.get('ok') else []
    if active:
        # 保持 GBK 终端兼容：避免输出 Emoji 等非 GBK 字符。
        print(f'\n有 {len(active)} 条待审批请求待处理：')
        for number, p in enumerate(active, start=1):
            print(f"  {number}. {p.get('action')}（输入“批准 {number}”或“取消 {number}”）")


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


def setup_security_mode_if_needed() -> None:
    """Offer first-run mode setup without silently enabling a high-risk mode."""
    from core.security_mode import is_configured

    if is_configured():
        return
    print('\nSecurity mode has not been configured. High-risk actions remain unavailable until setup finishes.')
    print('Choose: 1) single-user controlled mode  2) multi-user separation  (Enter to skip)')
    choice = safe_input('Security mode: ')
    if not choice:
        return
    from scripts.initialize_security import initialize_security

    try:
        if choice == '1':
            print(initialize_security('single_user_controlled'))
        elif choice == '2':
            operator_sid = safe_input('Operator Windows SID: ')
            approver_sid = safe_input('Approver Windows SID: ')
            print(initialize_security('multi_user_separation', operator_sid, approver_sid))
        else:
            print('Skipped: choose 1 or 2 at the next startup, or run scripts/initialize_security.py.')
    except (ValueError, FileExistsError) as exc:
        print(f'Security setup not completed: {exc}')


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
    setup_security_mode_if_needed()
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

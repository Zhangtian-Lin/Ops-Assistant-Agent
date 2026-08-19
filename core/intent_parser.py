"""LLM 意图解析模块：LLM 语义解析 + 规则兜底。

优先调用 LLM 把自然语言 query 解析为结构化意图；未配置 LLM 或解析失败时，
平滑降级到调用方传入的规则解析函数，保证离线可用。

环境变量（OpenAI 兼容接口）：
    LLM_API_KEY   必填，不配置则跳过 LLM 直接走规则
    LLM_BASE_URL  可选，默认 https://api.openai.com/v1
    LLM_MODEL     可选，默认 gpt-4o-mini
"""

from typing import Any, Callable, Dict, Optional

from core.llm import LLMClient

# 意图对象全集：LLM prompt 与校验逻辑共用
INTENT_OBJECTS = [
    'cpu',
    'memory',
    'disk',
    'disk_distribution',
    'service',
    'search',
    'audit',
    'knowledge',
    'memory_request',
    'memory_clear',
    'network',
    'approve',
    'cancel',
    'list_approvals',
]

INTENT_ACTIONS = ['check', 'control', 'none']

# 各 object 允许的参数字段：用于 LLM 填参 + 结果过滤（多余字段一律丢弃）
INTENT_ARGS_SCHEMA = {
    'cpu': [],
    'memory': [],
    'memory_clear': [],
    'network': ['query'],
    'disk': ['path'],
    'disk_distribution': ['path'],
    'service': ['service_name'],
    'search': ['query'],
    'audit': ['path'],
    'knowledge': ['query'],
    'memory_request': ['query'],
    'approve': ['request_id', 'confirmation'],
    'cancel': ['request_id'],
    'list_approvals': [],
}

INTENT_SYSTEM_PROMPT = (
    "你是运维 Agent 的意图解析器。把用户的指令解析成 JSON，只输出 JSON，不要任何解释。\n"
    "输出格式：{\"action\": \"<check|control|none>\", \"object\": \"<类型>\", \"args\": {<参数>}}\n"
    "可选 object 类型：cpu, memory, disk, disk_distribution, service, network, search, audit, knowledge, memory_request, memory_clear, approve, cancel, list_approvals\n"
    "映射规则：\n"
    "- 查询/检查 CPU → check + cpu；内存 → check + memory；磁盘 → check + disk；磁盘空间分布 → check + disk_distribution\n"
    "- 查询服务状态 → check + service\n"
    "- 查询网络、本机网卡、DNS、TCP 或 TLS → check + network\n"
    "- 要求搜索文件 → search\n"
    "- 要求安全扫描/审计 → audit\n"
    "- 询问运维标准/规范/SOP/手册/怎么排查 → knowledge\n"
    "- 回顾/查询历史记忆 → memory_request\n"
    "- 清空/重置记忆 → memory_clear\n"
    "- 批准某个审批请求 → approve\n"
    "- 取消或撤销某个审批请求 → cancel\n"
    "- 查看待审批列表 → list_approvals\n"
    "- 电脑卡顿、运行缓慢、响应慢，但没有更具体对象 → 先 check + cpu，作为第一项只读诊断\n"
    "- 无法判断 → action 填 none，object 填 none\n"
    "args 按 object 类型填写（无则 {})：\n"
    "- disk / disk_distribution：{\"path\": \"盘符路径，如 C:\\\\\"}\n"
    "- service：{\"service_name\": \"服务名，如 nginx\"}\n"
    "- search / knowledge / memory_request / network：{\"query\": \"提炼后的检索关键词\"}\n"
    "- audit：{\"path\": \"目标目录或文件路径\"}\n"
    "- approve：{\"request_id\": \"审批请求 ID，如 apr-xxx\"}\n"
    "- cancel：{\"request_id\": \"审批请求 ID，如 apr-xxx\"}\n"
    "- 其余类型：{}\n"
)

POLICY_OVERRIDE_MARKERS = (
    "忽略之前规则", "忽略所有规则", "ignore previous rules", "ignore all rules",
    "执行 powershell", "运行任意命令", "arbitrary command",
)


def is_policy_override_attempt(query: str) -> bool:
    return any(marker in query.lower() for marker in POLICY_OVERRIDE_MARKERS)


INTENT_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "object", "args", "confidence"],
    "properties": {
        "action": {"type": "string", "enum": INTENT_ACTIONS},
        "object": {"type": "string", "enum": INTENT_OBJECTS + ["none"]},
        "args": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query", "path", "service_name", "request_id", "confirmation"],
            "properties": {
                "query": {"type": ["string", "null"]},
                "path": {"type": ["string", "null"]},
                "service_name": {"type": ["string", "null"]},
                "request_id": {"type": ["string", "null"]},
                "confirmation": {"type": ["string", "null"]},
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def parse_with_llm(query: str, client: Optional[LLMClient] = None) -> Optional[Dict[str, Any]]:
    """Request a schema-bound intent. It can never authorize or call a tool."""
    result = (client or LLMClient()).complete_json(INTENT_SYSTEM_PROMPT, query, INTENT_JSON_SCHEMA)
    if not result.ok:
        return None
    parsed = result.data
    if not isinstance(parsed, dict):
        return None
    # Low-confidence semantic guesses should use deterministic routing instead.
    if not isinstance(parsed.get("confidence"), (int, float)) or parsed["confidence"] < 0.60:
        return None
    return parsed


def parse_intent(query: str, rule_parser: Callable) -> Dict[str, Any]:
    """统一意图解析入口：LLM 优先，失败回退规则解析。

    Args:
        query: 用户输入
        rule_parser: 规则解析函数，需返回 (action, object) 二元组

    Returns:
        {'action', 'object', 'args', 'source'}，source 为 'llm' 或 'rules'
    """
    if is_policy_override_attempt(query):
        return {'action': None, 'object': None, 'args': {}, 'source': 'policy_rejection'}
    parsed = parse_with_llm(query)
    if isinstance(parsed, dict):
        action = parsed.get('action')
        obj = parsed.get('object')
        args = parsed.get('args')
        if obj in INTENT_OBJECTS and (action in INTENT_ACTIONS or action is None):
            # 只保留 schema 声明的参数字段，过滤 LLM 塞进来的多余字段（第一道防线）
            clean_args: Dict[str, Any] = {}
            if isinstance(args, dict):
                allowed = set(INTENT_ARGS_SCHEMA.get(obj, []))
                clean_args = {k: v for k, v in args.items() if k in allowed}
            return {'action': action, 'object': obj, 'args': clean_args, 'source': 'llm'}

    # 回退规则解析
    try:
        action, obj = rule_parser(query)
    except Exception:
        action, obj = None, None
    return {'action': action, 'object': obj, 'args': {}, 'source': 'rules'}

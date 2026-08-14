"""LLM 意图解析模块：LLM 语义解析 + 规则兜底。

优先调用 LLM 把自然语言 query 解析为结构化意图；未配置 LLM 或解析失败时，
平滑降级到调用方传入的规则解析函数，保证离线可用。

环境变量（OpenAI 兼容接口）：
    LLM_API_KEY   必填，不配置则跳过 LLM 直接走规则
    LLM_BASE_URL  可选，默认 https://api.openai.com/v1
    LLM_MODEL     可选，默认 gpt-4o-mini
"""

import json
import os
from typing import Any, Callable, Dict, Optional

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
]

INTENT_ACTIONS = ['check', 'control', 'none']

INTENT_SYSTEM_PROMPT = (
    "你是运维 Agent 的意图解析器。把用户的指令解析成 JSON，只输出 JSON，不要任何解释。\n"
    "输出格式：{\"action\": \"<check|control|none>\", \"object\": \"<类型>\", \"args\": {}}\n"
    "可选 object 类型：cpu, memory, disk, disk_distribution, service, search, audit, knowledge, memory_request, memory_clear\n"
    "映射规则：\n"
    "- 查询/检查 CPU → check + cpu；内存 → check + memory；磁盘 → check + disk；磁盘空间分布 → check + disk_distribution\n"
    "- 查询服务状态 → check + service\n"
    "- 要求搜索文件 → search\n"
    "- 要求安全扫描/审计 → audit\n"
    "- 询问运维标准/规范/SOP/手册/怎么排查 → knowledge\n"
    "- 回顾/查询历史记忆 → memory_request\n"
    "- 清空/重置记忆 → memory_clear\n"
    "- 无法判断 → action=check 之外的 none，object 留空字符串\n"
)


def _get_llm_config() -> Optional[Dict[str, str]]:
    api_key = os.getenv('LLM_API_KEY') or os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None
    return {
        'api_key': api_key,
        'base_url': os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1'),
        'model': os.getenv('LLM_MODEL', 'gpt-4o-mini'),
    }


def parse_with_llm(query: str) -> Optional[Dict[str, Any]]:
    """调用 LLM 解析意图，失败返回 None。"""
    cfg = _get_llm_config()
    if not cfg:
        return None
    try:
        import requests
        resp = requests.post(
            f"{cfg['base_url'].rstrip('/')}/chat/completions",
            headers={'Authorization': f"Bearer {cfg['api_key']}"},
            json={
                'model': cfg['model'],
                'messages': [
                    {'role': 'system', 'content': INTENT_SYSTEM_PROMPT},
                    {'role': 'user', 'content': query},
                ],
                'temperature': 0,
            },
            timeout=10,
        )
        resp.raise_for_status()
        content = resp.json()['choices'][0]['message']['content'].strip()
        # 剥离可能的 ```json 围栏
        if content.startswith('```'):
            content = content.strip('`')
            if content.lower().startswith('json'):
                content = content[4:]
        return json.loads(content)
    except Exception:
        return None


def parse_intent(query: str, rule_parser: Callable) -> Dict[str, Any]:
    """统一意图解析入口：LLM 优先，失败回退规则解析。

    Args:
        query: 用户输入
        rule_parser: 规则解析函数，需返回 (action, object) 二元组

    Returns:
        {'action', 'object', 'args', 'source'}，source 为 'llm' 或 'rules'
    """
    parsed = parse_with_llm(query)
    if isinstance(parsed, dict):
        action = parsed.get('action')
        obj = parsed.get('object')
        args = parsed.get('args') or {}
        if obj in INTENT_OBJECTS and (action in INTENT_ACTIONS or action is None):
            return {'action': action, 'object': obj, 'args': args, 'source': 'llm'}

    # 回退规则解析
    try:
        action, obj = rule_parser(query)
    except Exception:
        action, obj = None, None
    return {'action': action, 'object': obj, 'args': {}, 'source': 'rules'}

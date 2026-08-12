import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_SESSION_HISTORY = 50
WORKSPACE_ROOT = Path(__file__).resolve().parent
MEMORY_DIR = WORKSPACE_ROOT / 'memory'
SESSION_HISTORY_FILE = MEMORY_DIR / 'session_history.json'
SESSION_SUMMARY_FILE = MEMORY_DIR / 'session_summary.json'
SESSION_INDEX_FILE = MEMORY_DIR / 'session_index.json'
SESSION_HISTORY: List[Dict[str, Any]] = []
SESSION_SUMMARY: Dict[str, Any] = {}
SESSION_INDEX: Dict[str, Any] = {}


def _ensure_memory_dir() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _load_session_history() -> None:
    _ensure_memory_dir()
    if not SESSION_HISTORY_FILE.exists():
        return
    try:
        data = json.loads(SESSION_HISTORY_FILE.read_text(encoding='utf-8'))
        if isinstance(data, list):
            SESSION_HISTORY.clear()
            SESSION_HISTORY.extend(data[-MAX_SESSION_HISTORY:])
    except Exception:
        SESSION_HISTORY.clear()


def _save_session_history() -> None:
    _ensure_memory_dir()
    SESSION_HISTORY_FILE.write_text(
        json.dumps(SESSION_HISTORY, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _load_session_summary() -> None:
    _ensure_memory_dir()
    if not SESSION_SUMMARY_FILE.exists():
        return
    try:
        data = json.loads(SESSION_SUMMARY_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            SESSION_SUMMARY.clear()
            SESSION_SUMMARY.update(data)
    except Exception:
        SESSION_SUMMARY.clear()


def _save_session_summary() -> None:
    _ensure_memory_dir()
    SESSION_SUMMARY_FILE.write_text(
        json.dumps(SESSION_SUMMARY, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _load_session_index() -> None:
    _ensure_memory_dir()
    if not SESSION_INDEX_FILE.exists():
        return
    try:
        data = json.loads(SESSION_INDEX_FILE.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            SESSION_INDEX.clear()
            SESSION_INDEX.update(data)
    except Exception:
        SESSION_INDEX.clear()


def _save_session_index() -> None:
    _ensure_memory_dir()
    SESSION_INDEX_FILE.write_text(
        json.dumps(SESSION_INDEX, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _extract_keywords(text: str) -> List[str]:
    tokens = re.findall(r'[a-zA-Z0-9_\u4e00-\u9fff]+', text.lower())
    stopwords = {
        '检查', '查看', '查询', '检测', '搜索', '记忆', '回顾', '历史',
        'service', 'memory', 'cpu', 'disk', 'check', 'search', 'result',
        'task', 'tool', 'question', 'service_name', 'path', 'status'
    }
    return [token for token in tokens if len(token) > 1 and token not in stopwords]


def _find_event_ids_for_query(query: str) -> List[str]:
    query_keywords = _extract_keywords(query)
    if not query_keywords:
        return []
    index = get_session_index()
    event_ids: List[str] = []
    for keyword in query_keywords:
        for event_id in index.get('keyword_index', {}).get(keyword, []):
            if event_id not in event_ids:
                event_ids.append(event_id)
    return event_ids


def _build_session_summary(last_n: int = 10) -> Dict[str, Any]:
    recent_history = SESSION_HISTORY[-last_n:]
    questions = [entry.get('question', '') for entry in recent_history]
    tool_names = [entry.get('task', {}).get('tool') for entry in recent_history]
    topics = []
    for question in questions:
        topics.extend(_extract_keywords(question))
    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'entry_count': len(SESSION_HISTORY),
        'recent_questions': questions,
        'recent_tool_usage': {tool: tool_names.count(tool) for tool in set(tool_names) if tool},
        'recent_topics': list(dict.fromkeys(topics))[:20],
        'summary_text': ' | '.join(questions[-5:]) if questions else '',
    }


def _build_session_index() -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    keyword_index: Dict[str, List[str]] = {}
    for entry in SESSION_HISTORY:
        event_id = entry.get('event_id')
        if not event_id:
            continue
        question = entry.get('question', '')
        tool = entry.get('task', {}).get('tool')
        keywords = set(_extract_keywords(question))
        if tool:
            keywords.add(tool)
        for keyword in keywords:
            keyword_index.setdefault(keyword, []).append(event_id)
        entries.append({
            'event_id': event_id,
            'timestamp': entry.get('timestamp'),
            'tool': tool,
            'question': question,
        })
    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'event_count': len(entries),
        'entries': entries,
        'keyword_index': keyword_index,
    }


def log_session_entry(question: str, task: Dict[str, Any], result: Dict[str, Any]) -> None:
    """记录一条会话历史，并持久化到文件。"""
    entry = {
        'event_id': f'evt-{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'question': question,
        'task': task,
        'result': result,
    }
    SESSION_HISTORY.append(entry)
    if len(SESSION_HISTORY) > MAX_SESSION_HISTORY:
        SESSION_HISTORY.pop(0)
    _save_session_history()
    update_session_summary()
    update_session_index()


def get_session_summary() -> Dict[str, Any]:
    """返回当前压缩记忆摘要。"""
    if not SESSION_SUMMARY and SESSION_HISTORY:
        update_session_summary()
    return SESSION_SUMMARY


def update_session_summary(last_n: int = 10) -> Dict[str, Any]:
    """生成并持久化当前压缩记忆摘要。"""
    SESSION_SUMMARY.clear()
    SESSION_SUMMARY.update(_build_session_summary(last_n=last_n))
    _save_session_summary()
    return SESSION_SUMMARY


def get_session_index() -> Dict[str, Any]:
    """返回当前索引结构。"""
    if not SESSION_INDEX and SESSION_HISTORY:
        update_session_index()
    return SESSION_INDEX


def update_session_index() -> Dict[str, Any]:
    """生成并持久化当前索引文件。"""
    SESSION_INDEX.clear()
    SESSION_INDEX.update(_build_session_index())
    _save_session_index()
    return SESSION_INDEX


def _get_history_by_event_ids(event_ids: List[str]) -> List[Dict[str, Any]]:
    id_set = set(event_ids)
    return [entry for entry in SESSION_HISTORY if entry.get('event_id') in id_set]


def query_session_history(query: str, last_n: Optional[int] = None) -> List[Dict[str, Any]]:
    """按关键词检索会话历史。"""
    q = query.lower().strip()
    if not q:
        return []
    event_ids = _find_event_ids_for_query(q)
    if event_ids:
        return _get_history_by_event_ids(event_ids)
    entries = SESSION_HISTORY[-last_n:] if last_n is not None else SESSION_HISTORY
    matches = []
    for entry in entries:
        text = ' '.join([
            entry.get('question', ''),
            str(entry.get('task', '')),
            str(entry.get('result', '')),
        ]).lower()
        if q in text:
            matches.append(entry)
    return matches


def search_memory(query: Optional[str] = None, max_entries: int = 10) -> Dict[str, Any]:
    """按 summary -> index -> history 顺序检索记忆。"""
    summary = get_session_summary()
    if query:
        event_ids = _find_event_ids_for_query(query)
        if event_ids:
            history = _get_history_by_event_ids(event_ids)[:max_entries]
        else:
            history = query_session_history(query, last_n=max_entries)
    else:
        history = SESSION_HISTORY[-max_entries:]
    return {
        'summary': summary,
        'query': query,
        'matched_history': history,
        'index': get_session_index(),
    }


def get_session_context_for_rag(query: Optional[str] = None, max_entries: int = 10) -> List[Dict[str, Any]]:
    """返回用于 RAG 的历史上下文条目。"""
    if query:
        matches = query_session_history(query, last_n=max_entries)
        if matches:
            return matches[:max_entries]
    return SESSION_HISTORY[-max_entries:]


def clear_session_history() -> None:
    """清空会话历史，并持久化变化。"""
    SESSION_HISTORY.clear()
    _save_session_history()
    SESSION_SUMMARY.clear()
    _save_session_summary()
    SESSION_INDEX.clear()
    _save_session_index()


_load_session_history()
_load_session_summary()
_load_session_index()

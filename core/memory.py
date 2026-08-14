import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core import vector_engine

MAX_SESSION_HISTORY = 50
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
MEMORY_DIR = WORKSPACE_ROOT / 'data' / 'memory'
SESSION_HISTORY_FILE = MEMORY_DIR / 'session_history.json'
SESSION_SUMMARY_FILE = MEMORY_DIR / 'session_summary.json'
SESSION_INDEX_FILE = MEMORY_DIR / 'session_index.json'
SESSION_ABSTRACTS_FILE = MEMORY_DIR / 'session_abstracts.json'
SESSION_HISTORY: List[Dict[str, Any]] = []
SESSION_SUMMARY: Dict[str, Any] = {}
SESSION_INDEX: Dict[str, Any] = {}
SESSION_ABSTRACTS: List[Dict[str, Any]] = []
PENDING_APPROVALS_FILE = MEMORY_DIR / 'pending_approvals.json'
PENDING_APPROVALS: List[Dict[str, Any]] = []


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


def _load_session_abstracts() -> None:
    _ensure_memory_dir()
    if not SESSION_ABSTRACTS_FILE.exists():
        return
    try:
        data = json.loads(SESSION_ABSTRACTS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, list):
            SESSION_ABSTRACTS.clear()
            SESSION_ABSTRACTS.extend(data)
    except Exception:
        SESSION_ABSTRACTS.clear()


def _save_session_index() -> None:
    _ensure_memory_dir()
    SESSION_INDEX_FILE.write_text(
        json.dumps(SESSION_INDEX, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _save_session_abstracts() -> None:
    _ensure_memory_dir()
    SESSION_ABSTRACTS_FILE.write_text(
        json.dumps(SESSION_ABSTRACTS, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _load_pending_approvals() -> None:
    _ensure_memory_dir()
    if not PENDING_APPROVALS_FILE.exists():
        return
    try:
        data = json.loads(PENDING_APPROVALS_FILE.read_text(encoding='utf-8'))
        if isinstance(data, list):
            PENDING_APPROVALS.clear()
            PENDING_APPROVALS.extend(data)
    except Exception:
        PENDING_APPROVALS.clear()


def _save_pending_approvals() -> None:
    _ensure_memory_dir()
    PENDING_APPROVALS_FILE.write_text(
        json.dumps(PENDING_APPROVALS, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _compress_entries(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compress a list of history entries into a lightweight archive object."""
    if not entries:
        return {}

    # Prefer to archive only high-value (long_term) entries to keep archives meaningful.
    long_entries = [e for e in entries if e.get('long_term')]
    event_ids = [e.get('event_id') for e in long_entries if e.get('event_id')]
    questions = [e.get('question', '') for e in long_entries]
    # If no long entries, fallback to compressing a lightweight summary of the oldest entries
    if not long_entries:
        event_ids = [e.get('event_id') for e in entries if e.get('event_id')]
        questions = [e.get('question', '') for e in entries]

    # Simple compression: join recent questions into a summary_text (trim to 1000 chars)
    summary_text = ' || '.join(questions)
    if len(summary_text) > 1000:
        summary_text = summary_text[:1000].rsplit(' ', 1)[0] + '...'
    return {
        'archived_at': datetime.utcnow().isoformat() + 'Z',
        'from_event': event_ids[0] if event_ids else None,
        'to_event': event_ids[-1] if event_ids else None,
        'event_count': len(event_ids),
        'event_ids': event_ids,
        'summary_text': summary_text,
        'dropped_count': max(0, len(entries) - len(event_ids)),
    }


def _build_abstract_from_history(recent_history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Create a simple abstract from recent history entries.

    This is intentionally lightweight: it aggregates topics and event_ids.
    """
    if not recent_history:
        return None
    # prefer long_term event ids when available
    long_ids = [e.get('event_id') for e in recent_history if e.get('long_term')]
    event_ids = long_ids if long_ids else [e.get('event_id') for e in recent_history if e.get('event_id')]
    text_parts = [e.get('question', '') for e in recent_history if e.get('question')]
    summary_text = ' | '.join(text_parts[:10])
    abstract = {
        'abstract_id': f'abs-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}',
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'text': summary_text,
        'event_ids': event_ids,
        'meta': {
            'from_count': len(recent_history),
            'long_term_count': len(long_ids),
        }
    }
    return abstract


def update_session_abstracts(last_n: int = 20) -> List[Dict[str, Any]]:
    """Generate or update abstracts based on recent history and persist them.

    - Creates a new abstract from recent entries and merges with existing abstracts if similar.
    """
    recent = SESSION_HISTORY[-last_n:]
    new_abs = _build_abstract_from_history(recent)
    if not new_abs:
        return SESSION_ABSTRACTS

    # naive dedup: if same text exists, merge event_ids
    for a in SESSION_ABSTRACTS:
        if a.get('text') == new_abs.get('text'):
            # merge event ids uniquely
            existing = set(a.get('event_ids', []))
            existing.update(new_abs.get('event_ids', []))
            a['event_ids'] = list(existing)
            a['generated_at'] = new_abs['generated_at']
            _save_session_abstracts()
            try:
                vector_engine.upsert_vector(a['abstract_id'], 'abstract', a.get('text', ''))
            except Exception:
                pass
            return SESSION_ABSTRACTS

    # otherwise append new abstract
    SESSION_ABSTRACTS.append(new_abs)
    _save_session_abstracts()
    try:
        vector_engine.upsert_vector(new_abs['abstract_id'], 'abstract', new_abs.get('text', ''))
    except Exception:
        pass
    return SESSION_ABSTRACTS


def enforce_capacity(max_entries: int = MAX_SESSION_HISTORY) -> None:
    """Ensure SESSION_HISTORY stays within max_entries by compressing and archiving old entries.

    This moves the oldest excess entries into `SESSION_SUMMARY['archives']` as compressed blobs.
    """
    if len(SESSION_HISTORY) <= max_entries:
        return
    # Number of entries to remove
    excess = len(SESSION_HISTORY) - max_entries
    # We'll archive the oldest `excess` entries as a single archive object.
    to_archive = SESSION_HISTORY[:excess]
    archive_obj = _compress_entries(to_archive)
    if archive_obj:
        archives = SESSION_SUMMARY.setdefault('archives', [])
        archives.append(archive_obj)
    # Remove archived entries from history
    del SESSION_HISTORY[:excess]
    # Persist changes
    _save_session_history()
    _save_session_summary()
    # Rebuild index to reflect removed events
    update_session_index()


def _create_pending_request(action: str, details: Dict[str, Any]) -> Dict[str, Any]:
    req = {
        'request_id': f'apr-{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}',
        'action': action,
        'details': details,
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat() + 'Z',
    }
    PENDING_APPROVALS.append(req)
    _save_pending_approvals()
    return req


def list_pending_approvals() -> List[Dict[str, Any]]:
    return list(PENDING_APPROVALS)


def request_clear_session_history(requester: Optional[str] = None) -> Dict[str, Any]:
    """Create a pending approval request to clear session history.

    Does NOT perform clearing. An approver must call `approve_request(request_id)`.
    """
    details = {'requester': requester}
    return _create_pending_request('clear_session_history', details)


def perform_clear_session_history() -> Dict[str, Any]:
    """Immediately clear history and persist. Intended to be called after approval."""
    SESSION_HISTORY.clear()
    _save_session_history()
    SESSION_SUMMARY.clear()
    _save_session_summary()
    SESSION_INDEX.clear()
    _save_session_index()
    SESSION_ABSTRACTS.clear()
    _save_session_abstracts()
    try:
        vector_engine.clear_all_vectors()
    except Exception:
        pass
    return {'status': 'cleared'}


def approve_request(request_id: str, approver: Optional[str] = None) -> Dict[str, Any]:
    for req in PENDING_APPROVALS:
        if req.get('request_id') == request_id and req.get('status') == 'pending':
            # mark approved
            req['status'] = 'approved'
            req['approved_at'] = datetime.utcnow().isoformat() + 'Z'
            req['approver'] = approver
            _save_pending_approvals()
            # 只做"批准"状态变更，返回动作名+参数；具体执行由上层（agent）查表分发
            return {
                'status': 'approved',
                'action': req.get('action'),
                'details': req.get('details', {}),
            }
    return {'status': 'not_found'}



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
    """记录一条会话历史，并持久化到文件与向量数据库。"""
    entry = {
        'event_id': f'evt-{datetime.utcnow().strftime("%Y%m%d%H%M%S%f")}',
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'question': question,
        'task': task,
        'result': result,
    }
    # Determine if this entry should be considered long-term (high-value)
    entry['long_term'] = _is_high_value_entry(question, task, result)
    SESSION_HISTORY.append(entry)

    # 向量持久化
    try:
        event_text = f"问：{question} | 工具：{task.get('tool')} | 结果：{str(result)}"
        vector_engine.upsert_vector(entry['event_id'], 'history', event_text)
    except Exception:
        pass

    # Enforce capacity: archive old entries when exceeding limit, otherwise persist normally
    if len(SESSION_HISTORY) > MAX_SESSION_HISTORY:
        enforce_capacity(MAX_SESSION_HISTORY)
    else:
        _save_session_history()
        update_session_summary()
        update_session_index()


def _is_high_value_entry(question: str, task: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Heuristic to decide whether an entry should be stored as long-term memory.

    Currently uses simple keyword and result-based rules. Can be extended later.
    """
    q = (question or '').lower()
    keywords = ['希望', '以后', '偏好', '记住', '请记住', '设置', '保存', 'always', 'prefer', 'preference', 'remember']
    if any(k in q for k in keywords):
        return True

    tool = (task or {}).get('tool')
    # Keep service errors and unexpected statuses as long-term facts
    if tool == 'check_service':
        status = (result or {}).get('status')
        if status in {'not_found', 'error'}:
            return True

    # Keep resource alerts
    if isinstance(result, dict):
        cpu = result.get('cpu_usage_percent')
        if isinstance(cpu, (int, float)) and cpu > 90:
            return True
        total = result.get('total_mb')
        used = result.get('used_mb')
        try:
            if total and used and float(used) / float(total) > 0.9:
                return True
        except Exception:
            pass

    return False


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
    # update abstracts when summary updates
    try:
        update_session_abstracts(last_n=last_n)
    except Exception:
        pass
    return SESSION_SUMMARY


def get_session_index() -> Dict[str, Any]:
    """返回当前索引结构。"""
    if not SESSION_INDEX and SESSION_HISTORY:
        update_session_index()
    return SESSION_INDEX


def get_session_abstracts() -> List[Dict[str, Any]]:
    """Return current abstracts list."""
    if not SESSION_ABSTRACTS and SESSION_HISTORY:
        update_session_abstracts()
    return SESSION_ABSTRACTS


def get_documents_by_ids(event_ids: List[str]) -> List[Dict[str, Any]]:
    """Return history entries for given event_ids in original order."""
    if not event_ids:
        return []
    id_set = set(event_ids)
    # preserve chronological order from SESSION_HISTORY
    return [entry for entry in SESSION_HISTORY if entry.get('event_id') in id_set]


def retrieve(query: Optional[str] = None, topk: int = 10) -> Dict[str, Any]:
    """High-level retrieval coordinator: summary -> keyword index -> vector index -> history.

    Returns a dict with keys: summary, abstract_matches, vector_matches, history_matches, index, conflict_warning
    """
    summary = get_session_summary()
    abstract_matches: List[Dict[str, Any]] = []
    vector_matches: List[Dict[str, Any]] = []
    history_matches: List[Dict[str, Any]] = []
    idx = get_session_index()
    matched_event_ids: List[str] = []

    if query:
        q = query.lower().strip()
        abstracts = get_session_abstracts()
        q_tokens = _extract_keywords(q)
        # 融合评分表：event_id -> 最终得分（关键词贡献精确分，向量贡献余弦分）
        fused_scores: Dict[str, float] = {}

        # 1) 关键词召回（精确命中，权重 1.0）——与向量召回并行，不再作为兜底
        for eid in _find_event_ids_for_query(q):
            fused_scores[eid] = fused_scores.get(eid, 0.0) + 1.0

        # 2) abstract 层关键词命中（同样属于精确召回）
        for a in abstracts:
            text = (a.get('text') or '').lower()
            if q in text or any(tok in text for tok in q_tokens):
                if a not in abstract_matches:
                    abstract_matches.append(a)
                for eid in a.get('event_ids', []):
                    fused_scores[eid] = fused_scores.get(eid, 0.0) + 1.0

        # 3) 向量语义召回（权重 = 余弦相似度）
        try:
            v_results = vector_engine.search_similar(q, top_k=topk)
            vector_matches = v_results
            for vr in v_results:
                v_id = vr.get('id')
                v_type = vr.get('type')
                v_score = float(vr.get('score', 0.0))
                if v_type == 'abstract':
                    for a in abstracts:
                        if a.get('abstract_id') == v_id:
                            if a not in abstract_matches:
                                abstract_matches.append(a)
                            for eid in a.get('event_ids', []):
                                fused_scores[eid] = fused_scores.get(eid, 0.0) + v_score
                elif v_type == 'history':
                    fused_scores[v_id] = fused_scores.get(v_id, 0.0) + v_score
        except Exception:
            pass

        # 4) 融合排序：按融合得分取 top_k
        ranked = sorted(fused_scores.items(), key=lambda kv: kv[1], reverse=True)
        matched_event_ids = [eid for eid, _ in ranked[:topk]]

        # 5) history 只负责按 event_id 取原始事实，不参与排序
        if matched_event_ids:
            history_matches = get_documents_by_ids(matched_event_ids)
        else:
            history_matches = query_session_history(q, last_n=topk)
    else:
        history_matches = SESSION_HISTORY[-topk:]

    # 简易事实冲突/覆盖检测 (根据概念文档第 50-51 条要求)
    conflict_warning = None
    if summary and history_matches:
        sum_text = summary.get('summary_text', '')
        recent_q = history_matches[-1].get('question', '') if history_matches else ''
        if recent_q and recent_q not in sum_text and summary.get('entry_count', 0) > len(history_matches):
            conflict_warning = "提示：匹配到的详细历史与摘要可能存在差异，以 matched_history 事实为准。"

    return {
        'summary': summary,
        'query': query,
        'abstract_matches': abstract_matches,
        'vector_matches': vector_matches,
        'history_matches': history_matches,
        'matched_history': history_matches,
        'index': idx,
        'conflict_warning': conflict_warning,
    }


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
    return retrieve(query, topk=max_entries)


def retrieve_knowledge(query: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
    """从静态知识库（item_type='knowledge'）检索相关内容。

    与个人历史记忆（item_type='history'）分离，用于 RAG 场景下的运维标准/SOP 召回。
    返回结果中的 text 已带「来源: 文件名」前缀（见 ingest_knowledge.py）。
    """
    if not query:
        return []
    try:
        return vector_engine.search_similar(query, top_k=top_k, item_type='knowledge')
    except Exception:
        return []


def get_session_context_for_rag(query: Optional[str] = None, max_entries: int = 10) -> List[Dict[str, Any]]:
    """返回用于 RAG 的历史上下文条目。"""
    res = retrieve(query, topk=max_entries)
    return res.get('matched_history', [])


def clear_session_history() -> None:
    """清空会话历史，并持久化变化。"""
    SESSION_HISTORY.clear()
    _save_session_history()
    SESSION_SUMMARY.clear()
    _save_session_summary()
    SESSION_INDEX.clear()
    _save_session_index()
    SESSION_ABSTRACTS.clear()
    _save_session_abstracts()
    try:
        vector_engine.clear_all_vectors()
    except Exception:
        pass


_load_session_history()
_load_session_summary()
_load_session_index()
_load_session_abstracts()
_load_pending_approvals()

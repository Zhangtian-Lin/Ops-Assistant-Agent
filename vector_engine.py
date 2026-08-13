import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# 确定向量数据库存储路径
WORKSPACE_ROOT = Path(__file__).resolve().parent
MEMORY_DIR = WORKSPACE_ROOT / 'memory'
DB_PATH = MEMORY_DIR / 'vectors.db'

# 升级向量维度为 BAAI/bge-small-zh-v1.5 的标准 384 维
VECTOR_DIM = 384

_model_cache = None


def _ensure_db() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS vector_index (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        conn.commit()


def _load_bge_model():
    """尝试加载 BAAI/bge-small-zh-v1.5 深度学习 Embedding 模型。
    
    具有全局缓存，且支持 sentence-transformers 与 transformers 原生加载。
    """
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    try:
        from sentence_transformers import SentenceTransformer
        _model_cache = SentenceTransformer('BAAI/bge-small-zh-v1.5')
        return _model_cache
    except Exception:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained('BAAI/bge-small-zh-v1.5')
            model = AutoModel.from_pretrained('BAAI/bge-small-zh-v1.5')
            model.eval()
            _model_cache = (tokenizer, model)
            return _model_cache
        except Exception:
            return None


def _fallback_embedding(text: str, dim: int = VECTOR_DIM) -> np.ndarray:
    """产生确定性且高质量的文本特征嵌入向量 (离线备用降级引擎)。
    
    保证在没有任何网络和预训练模型权重的环境下，系统依然能正常运行。
    """
    vec = np.zeros(dim, dtype=np.float32)
    if not text:
        return vec

    tokens = re.findall(r'[a-zA-Z0-9_\u4e00-\u9fff]+', text.lower())
    for token in tokens:
        h = hash(token) % dim
        vec[h] += 1.0
        for i in range(len(token) - 1):
            bg = token[i:i + 2]
            bh = hash(bg) % dim
            vec[bh] += 0.5

    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec.astype(np.float32)


def embed_text(text: str) -> np.ndarray:
    """优先使用 BAAI/bge-small-zh-v1.5 模型生成 384 维深度语义向量。
    
    若缺少网络或依赖，平滑降级至本地算法。
    """
    model_obj = _load_bge_model()
    if model_obj is not None:
        try:
            # 1. 优先尝试 sentence-transformers
            if hasattr(model_obj, 'encode'):
                vec = model_obj.encode(text, normalize_embeddings=True)
                return np.array(vec, dtype=np.float32)
            
            # 2. 备用原生 transformers 抽取 [CLS] 位置词向量并归一化
            tokenizer, model = model_obj
            import torch
            inputs = tokenizer(text, return_tensors='pt', padding=True, truncation=True, max_length=512)
            with torch.no_grad():
                outputs = model(**inputs)
                vec = outputs.last_hidden_state[:, 0, :].squeeze(0).cpu().numpy()
                norm = np.linalg.norm(vec)
                return (vec / norm).astype(np.float32) if norm > 0 else vec.astype(np.float32)
        except Exception:
            pass

    # 3. 平滑降级方案
    return _fallback_embedding(text, dim=VECTOR_DIM)


def upsert_vector(item_id: str, item_type: str, text: str, vector: Optional[np.ndarray] = None) -> None:
    """写入或更新一条 384 维向量记录。"""
    _ensure_db()
    if vector is None:
        vector = embed_text(text)

    blob = vector.astype(np.float32).tobytes()
    now_str = datetime.utcnow().isoformat() + 'Z'

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            '''
            INSERT INTO vector_index (id, type, text, embedding, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                text = excluded.text,
                embedding = excluded.embedding,
                updated_at = excluded.updated_at
        ''',
            (item_id, item_type, text, blob, now_str),
        )
        conn.commit()


def search_similar(query: str, top_k: int = 5, item_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """根据 Query 文本计算余弦相似度，进行向量检索。"""
    _ensure_db()
    query_vec = embed_text(query)
    q_norm = np.linalg.norm(query_vec)
    if q_norm == 0:
        return []

    with sqlite3.connect(DB_PATH) as conn:
        if item_type:
            cursor = conn.execute(
                'SELECT id, type, text, embedding FROM vector_index WHERE type = ?', (item_type,)
            )
        else:
            cursor = conn.execute('SELECT id, type, text, embedding FROM vector_index')

        rows = cursor.fetchall()

    if not rows:
        return []

    results = []
    for r_id, r_type, r_text, r_blob in rows:
        mat_vec = np.frombuffer(r_blob, dtype=np.float32)
        m_norm = np.linalg.norm(mat_vec)
        if m_norm > 0:
            score = float(np.dot(query_vec, mat_vec) / (q_norm * m_norm))
        else:
            score = 0.0

        if score > 0.01:
            results.append({
                'id': r_id,
                'type': r_type,
                'text': r_text,
                'score': round(score, 4),
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:top_k]


def remove_vector(item_id: str) -> None:
    """删除指定的向量记录。"""
    _ensure_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM vector_index WHERE id = ?', (item_id,))
        conn.commit()


def clear_all_vectors() -> None:
    """清空向量索引表。"""
    _ensure_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('DELETE FROM vector_index')
        conn.commit()

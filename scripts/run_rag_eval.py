"""Run reproducible source-retrieval RAG experiments without network access."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE_ROOT))

from core.rag import KnowledgeRetriever

KNOWLEDGE_DIR = WORKSPACE_ROOT / "data" / "knowledge_base"
CASES_PATH = WORKSPACE_ROOT / "eval" / "rag_cases.jsonl"
REPORT_PATH = WORKSPACE_ROOT / "reports" / "rag_eval_latest.json"
CHUNK_SIZES = (200, 500, 1000)
MODES = ("keyword", "vector", "hybrid")
TOP_K = 3


def recall_at_k(expected, sources, k):
    return int(bool(set(expected) & set(sources[:k])))


def reciprocal_rank(expected, sources):
    for rank, source in enumerate(sources, start=1):
        if source in expected:
            return 1 / rank
    return 0.0


def main() -> int:
    cases = [json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    experiments = []
    for chunk_size in CHUNK_SIZES:
        for mode in MODES:
            retriever = KnowledgeRetriever.from_directory(
                KNOWLEDGE_DIR,
                chunk_size=chunk_size,
                overlap=40,
                mode=mode,
            )
            records = []
            for case in cases:
                hits = retriever.search(case["question"], TOP_K)
                sources = list(dict.fromkeys(chunk.source for chunk, _score in hits))
                expected = case["expected_sources"]
                records.append({
                    "问题": case["question"],
                    "期望来源": expected,
                    "检索来源": sources,
                    "Recall@1": recall_at_k(expected, sources, 1),
                    "Recall@3": recall_at_k(expected, sources, 3),
                    "MRR": round(reciprocal_rank(expected, sources), 4),
                })
            experiments.append({
                "chunk_size": chunk_size,
                "chunk_overlap": 40,
                "retrieval_mode": mode,
                "embedding_mode": "runtime_embed_text",
                "shared_runtime_retriever": True,
                "chunk_count": len(retriever.chunks),
                "summary": {
                    "cases": len(records),
                    "Recall@1": round(mean(item["Recall@1"] for item in records), 4),
                    "Recall@3": round(mean(item["Recall@3"] for item in records), 4),
                    "MRR": round(mean(item["MRR"] for item in records), 4),
                },
                "records": records,
            })
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset": str(CASES_PATH.relative_to(WORKSPACE_ROOT)),
        "limitations": ["Demo knowledge base, not production SOP.", "Embedding quality depends on the runtime model availability and may fall back locally.", "Measures source retrieval only; does not claim answer faithfulness."],
        "experiments": experiments,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for experiment in experiments:
        summary = experiment["summary"]
        print(f"chunk={experiment['chunk_size']} mode={experiment['retrieval_mode']} R@1={summary['Recall@1']:.2%} R@3={summary['Recall@3']:.2%} MRR={summary['MRR']:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

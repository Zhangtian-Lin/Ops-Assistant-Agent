import base64
import subprocess
import sys

from core import memory
from core.rag import KnowledgeRetriever, chunk_markdown, hybrid_search, keyword_search, vector_search
from core.vector_engine import _fallback_embedding
from tests.evidence import EvidenceTestCase


class RAGEngineeringTests(EvidenceTestCase):
    def setUp(self):
        self.chunks = chunk_markdown(
            "# 网络排查\nDNS 解析失败时检查 DNS 服务器和解析结果。\n\n# 磁盘排查\nSMART 警告时先备份重要数据并检查硬盘健康。",
            "demo.md",
            100,
            overlap=20,
        )

    def test_chunking_preserves_source_and_respects_size(self):
        self.assertTrue(self.chunks)
        self.assertTrue(all(chunk.source == "demo.md" for chunk in self.chunks))
        self.assertTrue(all(len(chunk.text) <= 100 for chunk in self.chunks))
        self.record_evidence({"source": "demo.md", "chunk_size": 100}, "切块保留来源并不超过目标大小", {"chunk_count": len(self.chunks), "sources": sorted({chunk.source for chunk in self.chunks})})

    def test_retrievers_return_traceable_chunks(self):
        for search in (keyword_search, vector_search):
            hits = search("DNS 解析失败", self.chunks, 2)
            self.assertTrue(hits)
            self.assertEqual(hits[0][0].source, "demo.md")
        hybrid = hybrid_search("SMART 硬盘健康", self.chunks, 2)
        self.assertTrue(hybrid)
        self.record_evidence({"queries": ["DNS 解析失败", "SMART 硬盘健康"]}, "关键词、向量和混合检索均返回带来源的 Chunk", {"keyword_source": keyword_search("DNS 解析失败", self.chunks, 1)[0][0].source, "hybrid_source": hybrid[0][0].source})

    def test_runtime_and_eval_share_the_same_retriever(self):
        previous = memory._knowledge_retriever
        try:
            memory.reset_knowledge_retriever()
            retriever = memory.get_knowledge_retriever()
            self.assertIsInstance(retriever, KnowledgeRetriever)
            expected = retriever.search_records("SMART 硬盘健康", top_k=2)
            actual = memory.retrieve_knowledge("SMART 硬盘健康", top_k=2)
        finally:
            memory._knowledge_retriever = previous

        self.assertEqual(actual, expected)
        self.record_evidence(
            {"query": "SMART 硬盘健康", "top_k": 2},
            "Agent 运行时知识入口与 Eval 共用同一 KnowledgeRetriever",
            {
                "runtime_ids": [item["id"] for item in actual],
                "direct_ids": [item["id"] for item in expected],
                "identical": actual == expected,
            },
        )

    def test_fallback_embedding_is_stable_across_processes(self):
        local = base64.b64encode(_fallback_embedding("DNS 解析失败").tobytes()).decode("ascii")
        command = "from core.vector_engine import _fallback_embedding; import base64; print(base64.b64encode(_fallback_embedding('DNS 解析失败').tobytes()).decode('ascii'))"
        child = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, check=True)
        self.assertEqual(local, child.stdout.strip())
        self.record_evidence({"input": "DNS 解析失败", "processes": 2}, "降级 embedding 跨进程字节一致，评测可重复", {"bytes_equal": True})

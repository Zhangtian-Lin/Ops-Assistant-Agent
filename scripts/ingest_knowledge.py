import os
import sys
import hashlib
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(WORKSPACE_ROOT))

from core import vector_engine

KNOWLEDGE_DIR = WORKSPACE_ROOT / 'data' / 'knowledge_base'


def chunk_text(text: str, chunk_size: int = 400) -> list[str]:
    """简单的按字数切片，尽量按换行符分割，避免截断太生硬。"""
    lines = text.split('\n')
    chunks = []
    current_chunk = ""
    for line in lines:
        if len(current_chunk) + len(line) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = line + '\n'
        else:
            current_chunk += line + '\n'
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks


def ingest_all():
    # 确保知识库目录存在
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 前置安全扫描审计
    try:
        from core.security_scanner.scan_engine import ScanEngine
        print("正在对知识库目录执行前置安全扫描审计...")
        # 知识库属于文档类目录，不包含 NSEAP Skill 规范的 Manifest 结构，因此只筛选 R1-R6 代码安全规则评估
        engine = ScanEngine()
        scan_result = engine.scan_with_filter(str(KNOWLEDGE_DIR), [
            "R1_CREDENTIAL_LEAK",
            "R2_COMMAND_INJECTION",
            "R3_FILESYSTEM_RISK",
            "R4_NETWORK_RISK",
            "R5_PRIVILEGE_ESCALATION",
            "R6_DATA_EXFILTRATION"
        ])
        if scan_result.verdict == "BLOCK":
            print("[FAIL] [Security Audit Blocked] Knowledge directory safety scan failed. Rejects database ingestion!")
            print(f"Reason: {scan_result.summary}")
            for f in scan_result.findings:
                severity_rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
                if severity_rank.get(f.severity, 0) >= 3:
                    print(f"  - [{f.severity}] Rule triggered: {f.rule_name} | Location: {f.location}")
                    print(f"    Description: {f.description}")
                    print(f"    Remediation: {f.remediation}")
            return
        elif scan_result.findings:
            print("[WARN] [Security Audit Warning] Found low-risk findings (no block):")
            for f in scan_result.findings:
                print(f"  - [{f.severity}] {f.rule_name} (Location: {f.location})")
        else:
            print("[PASS] Security audit passed: No high-risk security issues detected.")
    except ImportError:
        print("[WARN] Warning: Security scanner not found. Skipping security audit.")
    except Exception as e:
        print(f"[WARN] Security audit process error: {e}, skipping security audit.")

    files = list(KNOWLEDGE_DIR.glob('**/*.txt')) + list(KNOWLEDGE_DIR.glob('**/*.md'))
    if not files:
        print(f"在 {KNOWLEDGE_DIR} 中没有找到 .txt 或 .md 文件。")
        return

    print(f"找到 {len(files)} 个知识文档，准备切片并存入数据库...")

    total_chunks = 0
    for file_path in files:
        try:
            content = file_path.read_text(encoding='utf-8')
            chunks = chunk_text(content)
            print(f"File {file_path.name} -> Chunked into {len(chunks)} pieces")

            for i, chunk in enumerate(chunks):
                if not chunk:
                    continue
                # 用 MD5 保证切片的 ID 唯一
                chunk_hash = hashlib.md5(chunk.encode('utf-8')).hexdigest()
                item_id = f"doc_{file_path.stem}_{i}_{chunk_hash[:8]}"

                # 存入数据库，标记类型为 'knowledge'
                vector_engine.upsert_vector(
                    item_id=item_id,
                    item_type='knowledge',
                    text=f"【来源: {file_path.name}】\n{chunk}"
                )
                total_chunks += 1
        except Exception as e:
            print(f"处理文件 {file_path} 时出错: {e}")

    print(f"Ingestion complete. Added {total_chunks} chunks to vectors.db.")


if __name__ == '__main__':
    ingest_all()

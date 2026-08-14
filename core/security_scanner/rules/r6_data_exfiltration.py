"""R6: 数据外泄风险检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding

# L5 — 环境变量读取后向外发送
EXFIL_ENV_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)(os\.environ|getenv|\.env|environ\[).*", "环境变量读取"),
]

# L4 — 敏感文件上传到外部
UPLOAD_PATTERNS: list[tuple[str, str]] = [
    (r"\bcurl\s+.*\s+-F\s+[\x27\x22]file=@", "curl 上传文件"),
    (r"\bcurl\s+.*\s+--data-binary\s+@", "curl 发送文件内容"),
    (r"\bwget\s+--post-file\s*=", "wget POST 发送文件"),
    (r"requests\.post\s*\([^)]*files\s*=", "requests 上传文件"),
]

# L3 — 文件内容外发
EXFIL_CONTENT_PATTERNS: list[tuple[str, str]] = [
    (r"\bcurl\s+\S+\s+-d\s+[\x60$\(]", "curl 动态发送内容"),
    (r"\bwget\s+--post-data\s*=\s*[\x60$\(]", "wget 动态发送内容"),
]

# L3 — HTTP POST 敏感数据
HTTP_POST_PATTERNS: list[tuple[str, str]] = [
    (r"requests\.post\s*\(\s*[\x27\x22]http://", "HTTP POST 明文传输"),
]

# 组合检测：同一上下文中读env后又外发
EXFIL_COMBO_PATTERN = re.compile(
    r"(os\.environ|getenv|\.env|environ\[).*?curl|requests\.post.*?\.env",
    re.DOTALL | re.IGNORECASE,
)


class R6DataExfiltration(BaseRule):
    rule_id = "R6_DATA_EXFILTRATION"
    rule_name = "数据外泄风险"
    cwe = "CWE-200/CWE-359"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        for content, source in self._iter_texts(skill):
            findings.extend(self._scan_text(content, source))
            # 组合模式检测（读env → 外发）
            findings.extend(self._scan_combo(content, source))

        return findings

        return findings

    def _scan_text(self, text: str, source: str) -> list[Finding]:
        findings: list[Finding] = []
        lines = text.split("\n")

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            if self._is_doc_context(line):
                continue

            # L4: 文件上传
            for pattern, desc in UPLOAD_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"数据外泄风险: {desc}",
                            remediation="避免上传本地文件到外部服务",
                        )
                    )

            # L3: 内容外发
            for pattern, desc in EXFIL_CONTENT_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"动态数据外发: {desc}",
                            remediation="确保数据脱敏后再传输",
                        )
                    )

            # L3: HTTP POST
            for pattern, desc in HTTP_POST_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"明文数据外泄: {desc}",
                            remediation="使用 HTTPS POST 传输数据",
                        )
                    )

        return findings

    def _scan_combo(self, text: str, source: str) -> list[Finding]:
        """检测'读取环境变量 → 向外发送'的组合模式"""
        findings: list[Finding] = []

        has_env_read = bool(re.search(r"(os\.environ|getenv|\.env|environ\[)", text, re.IGNORECASE))
        has_external_send = bool(re.search(r"(requests\.post|curl|wget)", text, re.IGNORECASE))

        if has_env_read and has_external_send:
            findings.append(
                self._make_finding(
                    severity="L5",
                    location=source,
                    matched="检测到环境变量读取 + 外部数据发送的组合模式",
                    description="可能将敏感环境变量外泄到外部服务",
                    remediation="避免将环境变量内容直接发送到外部；使用脱敏后的数据",
                )
            )

        return findings

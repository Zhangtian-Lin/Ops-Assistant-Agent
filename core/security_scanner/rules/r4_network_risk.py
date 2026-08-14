"""R4: 网络请求风险检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding

# L4 — SSRF 风险
SSRF_PATTERNS: list[tuple[str, str]] = [
    (r"requests\.(get|post|put|delete|patch)\s*\(\s*(url|endpoint|target|uri|host)\b", "SSRF: URL完全由变量控制"),
    (r"urllib\.request\.urlopen\s*\(\s*(url|target)\b", "SSRF: urllib URL变量控制"),
    (r"httpx\.(get|post)\s*\(\s*(url|target)\b", "SSRF: httpx URL变量控制"),
]

# L3 — HTTP 明文传输
HTTP_PATTERNS: list[tuple[str, str]] = [
    (r"requests\.\w+\s*\(\s*[\x27\x22]http://", "HTTP 明文请求"),
    (r"urllib\.request\.urlopen\s*\(\s*[\x27\x22]http://", "urllib HTTP 明文"),
    (r"httpx\.\w+\s*\(\s*[\x27\x22]http://", "httpx HTTP 明文"),
]

# L3 — curl/wget 未校验
CURL_PATTERNS: list[tuple[str, str]] = [
    (r"\bcurl\s+http://", "curl HTTP 明文"),
    (r"\bwget\s+http://", "wget HTTP 明文"),
]

# 误报白名单
SAFE_HOSTS = [
    r"localhost",
    r"127\.0\.0\.1",
    r"0\.0\.0\.0",
    r"\.local",
    r"\.internal",
]


def _is_safe_host(url: str) -> bool:
    for host in SAFE_HOSTS:
        if re.search(host, url):
            return True
    return False


class R4NetworkRisk(BaseRule):
    rule_id = "R4_NETWORK_RISK"
    rule_name = "网络请求风险"
    cwe = "CWE-319/CWE-918"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        for content, source in self._iter_texts(skill):
            findings.extend(self._scan_text(content, source))

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

            # L4: SSRF
            for pattern, desc in SSRF_PATTERNS:
                if re.search(pattern, line):
                    # 如果 URL 在注释中或明显是测试 → 跳过
                    if _is_safe_host(line):
                        continue
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"SSRF 风险: {desc}",
                            remediation="对用户传入的 URL 做白名单校验；配置请求超时",
                        )
                    )

            # L3: HTTP 明文
            for pattern, desc in HTTP_PATTERNS:
                if re.search(pattern, line):
                    if _is_safe_host(line):
                        continue
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"明文传输: {desc}",
                            remediation="使用 HTTPS 代替 HTTP；配置请求超时",
                        )
                    )

            # L3: curl/wget HTTP
            for pattern, desc in CURL_PATTERNS:
                if re.search(pattern, line):
                    if _is_safe_host(line):
                        continue
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"不安全下载: {desc}",
                            remediation="使用 HTTPS URL 并验证 TLS 证书",
                        )
                    )

        return findings

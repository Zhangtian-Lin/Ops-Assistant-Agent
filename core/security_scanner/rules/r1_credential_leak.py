"""R1: 凭证/密钥泄露检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding


# ── 高危密钥模式（L5）─────────────────────────────
CRITICAL_PATTERNS: list[tuple[str, str]] = [
    # OpenAI / 类OpenAI API Key
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI/类OpenAI API Key"),
    # Google API Key
    (r"AIza[0-9A-Za-z\-_]{35}", "Google API Key"),
    # GitHub Personal Access Token
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    # GitHub OAuth Token
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth Token"),
    # Slack Token
    (r"xox[bpras]-[a-zA-Z0-9-]+", "Slack Token"),
    # AWS Access Key ID
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
]

# ── 严重密钥模式（L4）─────────────────────────────
HIGH_PATTERNS: list[tuple[str, str]] = [
    # SSH/GPG 私钥
    (r"-----BEGIN\s+(RSA|EC|OPENSSH|DSA)\s+PRIVATE\s+KEY-----", "SSH/GPG 私钥"),
    # API Key = value 模式
    (
        r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key)\s*[:=]\s*['\"]?\S{8,}",
        "API Key 硬编码",
    ),
    # Password = value 模式
    (
        r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?\S{4,}",
        "密码硬编码",
    ),
    # Token = value 模式
    (
        r"(?i)(token|auth[_-]?token|access[_-]?token)\s*[:=]\s*['\"]?\S{8,}",
        "Token 硬编码",
    ),
    # JDBC 连接串含密码
    (
        r"jdbc:[a-z]+://[^/]+/[^?\s]+\?.*password=",
        "JDBC 连接串含密码",
    ),
    # MongoDB URI 含密码
    (
        r"mongodb://[^:]+:[^@]+@",
        "MongoDB URI 含密码",
    ),
]

# ── 误报白名单占位符───────────────────────────
FALSE_POSITIVE_PLACEHOLDERS = [
    r"YOUR_API_KEY",
    r"<token>",
    r"<your[-_]?api[-_]?key>",
    r"your[-_]?token[-_]?here",
    # 中文尖括号占位符
    r"<[^>]*\u4e00-\u9fff[^>]*>",   # <从环境变量读取> 等中文占位符
    r"\u4ece\u73af\u5883\u53d8\u91cf\u8bfb\u53d6",  # 从环境变量读取
]

# 文档上下文模式 — 这些行不应该被当作实际配置检测
DOC_CONTEXT_PATTERNS = [
    r"#.*(token|password|key).*[:=].*<",   # 注释中的占位符赋值
    r"(token|password|key)\s*[:=]\s*<",     # 值用尖括号包裹的占位符
]


def _mask_secret(text: str) -> str:
    """脱敏：保留前4后4字符"""
    if len(text) <= 8:
        return text[:2] + "***"
    return text[:4] + "***" + text[-4:]


def _is_false_positive(text: str) -> bool:
    """检查是否为占位符/环境变量读取"""
    for pattern in FALSE_POSITIVE_PLACEHOLDERS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    # 过滤环境变量读取模式
    if re.search(r"(os\.environ|os\.getenv|environ\.get|getenv\s*\()", text):
        return True
    # 过滤文档上下文中的占位符赋值（如 # token: <xxx>）
    for pattern in DOC_CONTEXT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


class R1CredentialLeak(BaseRule):
    rule_id = "R1_CREDENTIAL_LEAK"
    rule_name = "凭证/密钥泄露"
    cwe = "CWE-798"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        # 遍历 SKILL.md + 所有脚本文件
        for content, source in self._iter_texts(skill):
            findings.extend(self._scan_text(content, source))

        return findings

    def _scan_text(self, text: str, source: str) -> list[Finding]:
        findings: list[Finding] = []
        lines = text.split("\n")

        for i, line in enumerate(lines, 1):
            if _is_false_positive(line):
                continue

            # L5: 高危密钥模式
            for pattern, key_type in CRITICAL_PATTERNS:
                for match in re.finditer(pattern, line):
                    matched = match.group()
                    findings.append(
                        self._make_finding(
                            severity="L5",
                            location=f"{source}:{i}",
                            matched=_mask_secret(matched),
                            description=f"{key_type} 硬编码在 Skill 中",
                            remediation="使用环境变量或密钥管理服务存储敏感凭证",
                        )
                    )

            # L4: 严重密钥模式
            for pattern, key_type in HIGH_PATTERNS:
                for match in re.finditer(pattern, line):
                    matched = match.group()
                    if _is_false_positive(matched):
                        continue
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=_mask_secret(matched),
                            description=f"{key_type} 暴露在 Skill 中",
                            remediation="移除硬编码凭证，改用环境变量",
                        )
                    )

        return findings

"""R3: 文件系统越权风险检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding

# L4 — 破坏性操作
DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+-rf?\s+[/~]\S*", "rm -rf 系统路径破坏"),
    (r"\brm\s+-rf?\s+/", "rm -rf / 破坏性删除"),
    (r"\brmdir\s+/", "rmdir 系统路径"),
    (r"\bos\.remove\s*\(", "os.remove() 文件删除"),
    (r"\bos\.unlink\s*\(", "os.unlink() 文件删除"),
    (r"\bshutil\.rmtree\s*\(", "shutil.rmtree() 递归删除"),
]

# L4 — 权限过度开放
PERMISSION_PATTERNS: list[tuple[str, str]] = [
    (r"\bchmod\s+777\b", "chmod 777 权限过度开放"),
    (r"\bchmod\s+-R\s+777\b", "chmod -R 777 递归开放"),
    (r"\bchmod\s+o\+w\b", "chmod o+w 其他用户写权限"),
    (r"\bos\.chmod\s*\([^)]*0o777", "os.chmod 777"),
]

# L3 — 越权路径访问
PATH_PATTERNS: list[tuple[str, str]] = [
    (r"/(etc|var|boot|sys|proc|dev|root|home)/", "系统敏感目录操作"),
    (r"\b/etc/(passwd|shadow|sudoers|crontab)\b", "系统关键文件操作"),
    (r"\.\.\/\.\.\/", "多级路径遍历 ../"),
    (r"open\s*\(\s*[\x27\x22]/", "使用绝对路径打开文件"),
]

# 误报白名单
SAFE_PATHS = [
    r"/home/",
    r"/tmp/",
    r"/logs/",
    r"/data/",
    r"/cache/",
    r"/workspace/",
    r"/app/",
    r"/usr/local/",
    r"/opt/",
]


def _is_safe_path(line: str) -> bool:
    """排除用户数据目录的合理访问"""
    for path in SAFE_PATHS:
        if path in line.lower():
            return True
    return False


class R3FilesystemRisk(BaseRule):
    rule_id = "R3_FILESYSTEM_RISK"
    rule_name = "文件系统越权风险"
    cwe = "CWE-22/CWE-732"

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

            # L4: 破坏性操作
            for pattern, desc in DESTRUCTIVE_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"破坏性文件操作: {desc}",
                            remediation="限定操作范围在 Skill 目录内，避免删除系统路径",
                        )
                    )

            # L4: 权限过度开放
            for pattern, desc in PERMISSION_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"权限过度开放: {desc}",
                            remediation="使用最小权限原则，如 chmod 644/chmod 755",
                        )
                    )

            # L3: 越权路径
            for pattern, desc in PATH_PATTERNS:
                if re.search(pattern, line):
                    if _is_safe_path(stripped):
                        continue
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"敏感路径访问: {desc}",
                            remediation="使用 pathlib.Path.resolve() 规范化后检查路径范围",
                        )
                    )

        return findings

"""R5: 权限提升风险检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding

# L5 — SUID/SGID 设置
SUID_PATTERNS: list[tuple[str, str]] = [
    (r"\bchmod\s+[46][0-7]{2,3}\b", "chmod 设置 SUID/SGID 位"),
    (r"\bchmod\s+[gu]\+s\b", "chmod +s 设置 SUID/SGID"),
    (r"\bchown\s+root:", "chown 将文件所有者改为 root"),
]

# L4 — 提权执行
SUDO_PATTERNS: list[tuple[str, str]] = [
    (r"\bsudo\s+(?!-)(?!apt\b)(?!yum\b)(?!npm\b)(?!pip\b)(?!brew\b)", "sudo 非包管理器命令"),
    (r"\bsu\s+-\s+\w+", "su 用户切换"),
    (r"\bdoas\b", "doas 提权执行"),
    (r"\bpkexec\b", "pkexec 提权执行"),
]

# L3 — 容器特权模式
CONTAINER_PATTERNS: list[tuple[str, str]] = [
    (r"--privileged\b", "Docker 特权容器模式"),
    (r"--cap-add\s*=\s*ALL\b", "容器添加全部能力"),
    (r"securityContext:\s*\n\s*privileged:\s*true", "K8s 特权容器"),
    (r"allowPrivilegeEscalation:\s*true", "K8s 允许提权"),
]


class R5PrivilegeEscalation(BaseRule):
    rule_id = "R5_PRIVILEGE_ESCALATION"
    rule_name = "权限提升风险"
    cwe = "CWE-269"

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

            # L5: SUID/SGID
            for pattern, desc in SUID_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L5",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"提权高危操作: {desc}",
                            remediation="不要设置 SUID/SGID 位；使用标准权限模型",
                        )
                    )

            # L4: sudo/提权执行
            for pattern, desc in SUDO_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"提权执行: {desc}",
                            remediation="避免使用 sudo，以最小权限运行 Agent",
                        )
                    )

            # L3: 容器特权
            for pattern, desc in CONTAINER_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"容器特权模式: {desc}",
                            remediation="去除 --privileged，按需添加 --cap-add；使用 SecurityContext",
                        )
                    )

        return findings

"""R2: 命令注入风险检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding

# L5 — 用户输入直接拼接进命令
CRITICAL_PATTERNS: list[tuple[str, str]] = [
    (r"os\.system\s*\(\s*f[\x27\x22]", "os.system(f...) 格式化字符串拼接"),
    (r"subprocess\.\w+\s*\([^)]*shell\s*=\s*True", "subprocess shell=True"),
    (r"os\.popen\s*\(", "os.popen 命令执行"),
]

# L4 — 系统调用无过滤
HIGH_PATTERNS: list[tuple[str, str]] = [
    (r"\bos\.system\s*\(", "os.system() 调用"),
    (r"\beval\s*\(", "eval() 动态执行"),
    (r"\bexec\s*\(", "exec() 动态执行"),
    (r"\binput\s*\(\s*\)", "input() 裸调用"),
    (r"\bexecfile\s*\(", "execfile() 调用"),
    (r"\bcompile\s*\(.*\)\s*\)", "compile() 动态编译后执行"),
]

# L3 — 拼接式命令执行（curl/wget 管道）
MEDIUM_PATTERNS: list[tuple[str, str]] = [
    (r"curl\s+\S+\s*\|\s*(ba)?sh\b", "curl 管道到 shell"),
    (r"wget\s+\S+\s+-O\s*-\s*\|\s*(ba)?sh\b", "wget 管道到 shell"),
    (r"\|\s*(ba)?sh\b", "管道直接进入 shell"),
    (r"pip\s+install\s+\S+\s*\|\s*(ba)?sh\b", "pip install 管道到 shell"),
]

# 误报白名单
SAFE_COMMANDS = [
    r"echo\s+",
    r"ls\s+",
    r"pwd\s*$",
    r"date\s*$",
    r"hostname\s*$",
    r"whoami\s*$",
    r"uname\s+",
    r"print\s*\(.*\)",
]


def _is_safe_call(line: str) -> bool:
    """排除明显无害的系统调用（如 os.system("echo hello")）"""
    for pattern in SAFE_COMMANDS:
        if re.search(pattern, line):
            return True
    return False


class R2CommandInjection(BaseRule):
    rule_id = "R2_COMMAND_INJECTION"
    rule_name = "命令注入风险"
    cwe = "CWE-78"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        for content, source in self._iter_texts(skill):
            # P2: 文本预清洗（去除三引号块、行内注释），降低误报
            cleaned = self._clean_text(content)
            findings.extend(self._scan_text(cleaned, source))

        return findings

    def _scan_text(self, text: str, source: str) -> list[Finding]:
        findings: list[Finding] = []
        lines = text.split("\n")

        for i, line in enumerate(lines, 1):
            # 跳过注释行和文档上下文
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            if self._is_doc_context(line):
                continue

            # L5: 高危
            for pattern, desc in CRITICAL_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L5",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"高危命令注入: {desc}",
                            remediation="使用 subprocess.run(['cmd', 'arg'], shell=False) 或避免动态拼接命令",
                        )
                    )

            # L4: 严重
            for pattern, desc in HIGH_PATTERNS:
                if re.search(pattern, line):
                    if _is_safe_call(stripped):
                        continue
                    findings.append(
                        self._make_finding(
                            severity="L4",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"命令注入风险: {desc}",
                            remediation="避免使用 eval/exec/os.system，改用安全的 API 调用",
                        )
                    )

            # L3: 中等
            for pattern, desc in MEDIUM_PATTERNS:
                if re.search(pattern, line):
                    findings.append(
                        self._make_finding(
                            severity="L3",
                            location=f"{source}:{i}",
                            matched=stripped[:80],
                            description=f"不安全的管道执行: {desc}",
                            remediation="避免使用 curl | bash 模式，改用包管理器或校验后再执行",
                        )
                    )

        return findings

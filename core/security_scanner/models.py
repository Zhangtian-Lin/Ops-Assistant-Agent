"""核心数据模型"""

from dataclasses import dataclass, field


@dataclass
class Skill:
    """一个 Skill 的结构化表示"""

    path: str  # 绝对路径
    name: str  # Skill 名称
    skill_md: str  # SKILL.md 全文
    files: list[str] = field(default_factory=list)  # 目录下文件列表
    file_contents: dict[str, str] = field(default_factory=dict)  # 文件名 → 内容


@dataclass
class Finding:
    """一条风险发现"""

    rule_id: str  # 规则 ID，如 "R1_CREDENTIAL_LEAK"
    rule_name: str  # 人类可读名称
    severity: str  # ECS 等级: "L0" ~ "L5"
    cwe: str  # CWE 编号
    location: str  # 触发位置，如 "SKILL.md:9"
    matched: str  # 命中文本（脱敏后）
    description: str  # 风险描述
    remediation: str  # 修复建议


@dataclass
class ScanResult:
    """一次扫描的完整结果"""

    skill: Skill
    findings: list[Finding] = field(default_factory=list)
    verdict: str = "PASS"  # "PASS" | "BLOCK"
    max_severity: str = "L0"
    summary: str = ""

    def compute_verdict(self):
        """根据 findings 自动计算 verdict 和 max_severity"""
        if not self.findings:
            self.verdict = "PASS"
            self.max_severity = "L0"
            self.summary = "未发现安全风险"
            return

        severity_rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
        max_s = max(self.findings, key=lambda f: severity_rank.get(f.severity, 0))
        self.max_severity = max_s.severity

        if any(severity_rank.get(f.severity, 0) >= 3 for f in self.findings):
            self.verdict = "BLOCK"
            blocker_count = sum(1 for f in self.findings if severity_rank.get(f.severity, 0) >= 3)
            self.summary = f"发现 {len(self.findings)} 个风险，其中 {blocker_count} 个达到 BLOCK 级别（≥L3），最高等级 {self.max_severity}"
        else:
            self.verdict = "PASS"
            self.summary = f"发现 {len(self.findings)} 个低风险项，无需阻断"

"""规则引擎 — 注册、调度、汇总扫描结果"""

from .parser import parse_skill
from .models import Skill, ScanResult
from .rules import ALL_RULES, BaseRule


class ScanEngine:
    """Skill 安全扫描引擎"""

    def __init__(self, rules: list[type[BaseRule]] | None = None):
        """初始化引擎。

        Args:
            rules: 要使用的规则类列表，默认使用 ALL_RULES
        """
        self.rules = rules or ALL_RULES

    def scan(self, skill_dir: str) -> ScanResult:
        """对一个 Skill 目录执行全量扫描。

        Args:
            skill_dir: Skill 目录路径

        Returns:
            ScanResult: 包含所有风险发现和 verdict 的扫描结果
        """
        # 1. 解析 Skill
        raw = parse_skill(skill_dir)
        skill = Skill(
            path=raw["path"],
            name=raw.get("name", skill_dir),
            skill_md=raw["skill_md"],
            files=raw["files"],
            file_contents=raw.get("file_contents", {}),
        )

        # 2. 逐条规则执行
        all_findings = []
        for RuleClass in self.rules:
            rule = RuleClass()
            findings = rule.inspect(skill)
            all_findings.extend(findings)

        # 3. 汇总 & 判定
        result = ScanResult(skill=skill, findings=all_findings)
        result.compute_verdict()

        return result

    def scan_with_filter(
        self, skill_dir: str, rule_ids: list[str]
    ) -> ScanResult:
        """按规则 ID 筛选后扫描。

        Args:
            skill_dir: Skill 目录路径
            rule_ids: 要执行的规则 ID 列表，如 ["R1_CREDENTIAL_LEAK", "R2_COMMAND_INJECTION"]

        Returns:
            ScanResult
        """
        filtered = [r for r in self.rules if r.rule_id in rule_ids]
        return ScanEngine(rules=filtered).scan(skill_dir)

    def scan_with_level(
        self, skill_dir: str, min_level: str
    ) -> ScanResult:
        """扫描并仅保留 >= min_level 的发现。

        Args:
            skill_dir: Skill 目录路径
            min_level: 最低等级，如 "L3"

        Returns:
            ScanResult（findings 已过滤，verdict 基于过滤后重新计算）
        """
        result = self.scan(skill_dir)
        original_count = len(result.findings)
        level_rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
        threshold = level_rank.get(min_level, 0)
        result.findings = [
            f for f in result.findings if level_rank.get(f.severity, 0) >= threshold
        ]
        # 基于过滤后的 findings 重新判定 verdict（确保一致）
        result.compute_verdict()
        if original_count != len(result.findings):
            result.summary += f"（已按 ≥{min_level} 过滤，原始共 {original_count} 个发现）"
        return result


def scan_skill(skill_dir: str) -> ScanResult:
    """便捷函数：用默认规则集扫描一个 Skill 目录。"""
    return ScanEngine().scan(skill_dir)

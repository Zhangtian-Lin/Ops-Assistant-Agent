"""Markdown 可读报告生成器"""

from datetime import datetime

from ..models import ScanResult, Finding

SEVERITY_ICON = {
    "L0": "[INFO]",
    "L1": "[LOW]",
    "L2": "[MED]",
    "L3": "[HIGH]",
    "L4": "[CRIT]",
    "L5": "[EMERG]",
}


def _escape_md(text: str) -> str:
    """转义 Markdown 特殊字符"""
    return text.replace("|", "\\|").replace("\n", " ")


def generate_markdown(result: ScanResult) -> str:
    """生成 Markdown 格式可读报告。

    Args:
        result: 扫描结果

    Returns:
        Markdown 格式字符串
    """
    lines = []

    # 标题
    lines.append("# Skill Security Scan Report")
    lines.append("")
    lines.append(f"**扫描时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Skill 信息
    lines.append("## 扫描对象")
    lines.append("")
    lines.append(f"| 属性 | 值 |")
    lines.append(f"|---|---|")
    lines.append(f"| 路径 | {result.skill.path} |")
    lines.append(f"| 名称 | {result.skill.name} |")
    lines.append(f"| 文件数 | {len(result.skill.files)} |")
    lines.append("")

    # Verdict
    verdict_icon = "PASS" if result.verdict == "PASS" else "BLOCK"
    lines.append(f"## 判定: **{verdict_icon}**")
    lines.append("")
    lines.append(f"> {result.summary}")
    lines.append(f"> 最高风险等级: **{result.max_severity}**")
    lines.append("")

    # 风险分布
    lines.append("## 风险分布")
    lines.append("")
    lines.append("| 等级 | 数量 |")
    lines.append("|---|---|")
    for level in ["L5", "L4", "L3", "L2", "L1", "L0"]:
        count = sum(1 for f in result.findings if f.severity == level)
        if count > 0:
            icon = SEVERITY_ICON.get(level, "")
            lines.append(f"| {icon} {level} | {count} |")
    lines.append(f"| **合计** | **{len(result.findings)}** |")
    lines.append("")

    if not result.findings:
        lines.append("**未发现安全风险**")
        return "\n".join(lines)

    # 逐条发现
    lines.append("## 风险详情")
    lines.append("")

    severity_order = {"L5": 0, "L4": 1, "L3": 2, "L2": 3, "L1": 4, "L0": 5}
    sorted_findings = sorted(
        result.findings, key=lambda f: severity_order.get(f.severity, 99)
    )

    for i, f in enumerate(sorted_findings, 1):
        icon = SEVERITY_ICON.get(f.severity, "")
        lines.append(f"### {i}. {icon} [{f.severity}] {f.rule_name}")
        lines.append("")
        lines.append(f"| 属性 | 值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 规则 ID | `{f.rule_id}` |")
        lines.append(f"| CWE | {f.cwe} |")
        lines.append(f"| 位置 | `{f.location}` |")
        lines.append(f"| 描述 | {f.description} |")
        lines.append("")
        lines.append(f"**命中文本**: `{_escape_md(f.matched)}`")
        lines.append("")
        lines.append(f"**修复建议**: {f.remediation}")
        lines.append("")

    # 修复总结
    lines.append("---")
    lines.append("")
    lines.append(f"*报告由 AI Security Skill Scanner 自动生成*")
    lines.append("")

    return "\n".join(lines)

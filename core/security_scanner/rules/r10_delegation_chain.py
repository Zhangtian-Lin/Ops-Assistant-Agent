"""R10: 委托链越权检测"""

import re

from .base import BaseRule
from ..models import Skill, Finding
from ..parser import parse_manifest

# 跨 Agent 调用模式
CROSS_AGENT_PATTERNS = [
    (r"call_agent\s*\(\s*[\x27\x22]([^\x27\x22]+)", "call_agent 调用"),
    (r"delegate_to\s*\(\s*[\x27\x22]([^\x27\x22]+)", "delegate_to 调用"),
    (r"agent://([\w-]+)/", "Agent URL 引用"),
    (r"invoke_agent\s*\(\s*[\x27\x22]([^\x27\x22]+)", "invoke_agent 调用"),
]


def _extract_called_agents(text: str) -> set[str]:
    """从代码中提取所有被调用的 Agent 名称"""
    agents = set()
    for pattern, _ in CROSS_AGENT_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            agents.add(m.group(1).strip())
    return agents


class R10DelegationChain(BaseRule):
    rule_id = "R10_DELEGATION_CHAIN"
    rule_name = "委托链越权"
    cwe = "CWE-862"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        manifest = parse_manifest(skill.path)
        if manifest is None:
            return findings

        declared = set(manifest.depends_on)
        called = _extract_called_agents(skill.skill_md)

        # 未声明的 Agent 调用
        undeclared = called - declared
        if undeclared:
            findings.append(
                self._make_finding(
                    severity="L4",
                    location="manifest.yaml + SKILL.md",
                    matched=f"代码中调用了未在 depends_on 中声明的 Agent: {', '.join(sorted(undeclared))}",
                    description=f"调用了 {len(undeclared)} 个未声明的 Agent，违反委托链规则",
                    remediation=f"在 manifest.yaml 的 depends_on 中声明: {', '.join(sorted(undeclared))}",
                )
            )

        # 反向检查：声明的 Agent 在代码中是否有对应调用
        unused = declared - called
        if unused:
            findings.append(
                self._make_finding(
                    severity="L2",
                    location="manifest.yaml",
                    matched=f"depends_on 中声明的 Agent 未在代码中找到调用: {', '.join(sorted(unused))}",
                    description="Manifest 声明了依赖但代码中未实际调用，建议清理或确认",
                    remediation=f"检查 {', '.join(sorted(unused))} 是否确实需要依赖",
                )
            )

        return findings

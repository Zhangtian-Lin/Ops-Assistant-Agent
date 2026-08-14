"""风险规则基类"""

import re
from abc import ABC, abstractmethod

from ..models import Skill, Finding


class BaseRule(ABC):
    """所有风险规则的抽象基类"""

    rule_id: str = ""
    rule_name: str = ""
    cwe: str = ""

    @abstractmethod
    def inspect(self, skill: Skill) -> list[Finding]:
        """检查 Skill，返回发现的风险列表"""
        ...

    def _iter_texts(self, skill: Skill) -> list[tuple[str, str]]:
        """返回 Skill 中所有可扫描的文本源。

        Returns:
            [(content, source_label), ...]
            source_label 如 "SKILL.md", "script.py", "utils.sh"
        """
        texts: list[tuple[str, str]] = []

        # SKILL.md 始终包含
        if skill.skill_md:
            texts.append((skill.skill_md, "SKILL.md"))

        # 追加所有脚本文件
        for filename, content in skill.file_contents.items():
            texts.append((content, filename))

        return texts

    # ── 文档上下文关键词（教学/反例/说明，不是真实代码）────
    DOC_CONTEXT_PATTERNS = [
        r"(错误|反面|不良)\s*(示例|例子|示范)",      # 错误示例 / 反例
        r"(不要|禁止|避免|切勿|请勿)\s*(使用|执行|调用|访问|操作)",  # 安全建议
        r"(Q|问|问题|FAQ)[:：]\s*",                 # 问答形式
        r"(A|答|回答)[:：]\s*",                     # 问答形式
        r"安全建议[:：]",                            # 安全建议段落
        r"为什么.*(不能|不要|禁止)",                  # 解释性句子
        r"注意[:：]",                               # 注意事项
        r"说明[:：]",                               # 说明段落
    ]

    @staticmethod
    def _is_doc_context(line: str) -> bool:
        """判断当前行是否为文档/教学上下文（非真实代码）。

        如果命中，说明这行是在讲解安全知识，不应该当作真实风险。
        """
        for pattern in BaseRule.DOC_CONTEXT_PATTERNS:
            if re.search(pattern, line):
                return True
        return False

    @staticmethod
    def _clean_text(text: str) -> str:
        """文本预清洗，降低误报率。

        1. 移除行内注释（# 后内容），但保留字符串内的 # 号和代码结构
        2. 移除三引号文档字符串/示例代码块（\"\"\"...\"\"\" 和 '''...'''）
        3. 移除 Markdown 代码围栏标记（```），避免标记行被误判

        Args:
            text: 原始文本

        Returns:
            清洗后的文本（仅用于扫描，不影响报告中的匹配文本）
        """
        # 步骤1: 移除三引号块（通常是 docstring 或 Markdown 示例代码）
        text = re.sub(r'""".*?"""', '', text, flags=re.DOTALL)
        text = re.sub(r"'''.*?'''", '', text, flags=re.DOTALL)

        # 步骤2: 逐行去除行内注释
        cleaned_lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            # 保留整行注释（已有 separate 处理），跳过空行
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                cleaned_lines.append(line)
                continue

            # 行内注释: 找到第一个不在字符串内的 #
            # 简化处理: 如果 # 前面不是引号包围的内容，视为注释
            hash_pos = line.find("#")
            if hash_pos > 0:
                before = line[:hash_pos]
                # 简单判断: 如果前面引号配对，说明 # 在代码中
                if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
                    cleaned_lines.append(line[:hash_pos].rstrip())
                    continue
            cleaned_lines.append(line)

        # 步骤3: 移除 Markdown 代码围栏行（```python, ```bash 等）
        result = "\n".join(cleaned_lines)
        result = re.sub(r"^```\w*\s*$", "", result, flags=re.MULTILINE)
        result = re.sub(r"^```\s*$", "", result, flags=re.MULTILINE)

        return result

    def _make_finding(
        self,
        severity: str,
        location: str,
        matched: str,
        description: str,
        remediation: str,
    ) -> Finding:
        return Finding(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=severity,
            cwe=self.cwe,
            location=location,
            matched=matched,
            description=description,
            remediation=remediation,
        )

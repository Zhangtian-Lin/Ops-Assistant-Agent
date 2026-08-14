"""R8: 权限声明与代码一致性检查"""

import re

from .base import BaseRule
from ..models import Skill, Finding
from ..parser import parse_manifest

# 代码模式 → 需要的权限
CODE_PERMISSION_MAP = {
    "filesystem_write": [
        (r"open\s*\(\s*\S+\s*,\s*[\x27\x22][wa]", "open(..., 'w'/'a') 写文件"),
        (r"\bos\.remove\s*\(|\bos\.unlink\s*\(|\bshutil\.rmtree\s*\(", "文件删除操作"),
        (r"\bchmod\s+", "chmod 修改权限"),
    ],
    "network": [
        (r"\brequests\.(get|post|put|delete|patch)\s*\(", "HTTP 请求"),
        (r"\burllib\.request\.urlopen\s*\(", "urllib HTTP 请求"),
        (r"\bhttpx\.\w+\s*\(", "httpx HTTP 请求"),
        (r"\bcurl\s+\S+", "curl 网络请求"),
        (r"\bwget\s+\S+", "wget 网络请求"),
    ],
    "commands": [
        (r"\bos\.system\s*\(|\bos\.popen\s*\(|\bsubprocess\.\w+\s*\(", "系统命令执行"),
    ],
}

MANIFEST_PERMISSION_MAP = {
    "filesystem": {
        "read": "filesystem_read",
        "write": "filesystem_write",
        "none": None,
    },
    "network": {
        "all": "network",
        "whitelist": "network",
        "none": None,
    },
    "commands": {
        "all": "commands",
        "whitelist": "commands",
        "none": None,
    },
}


class R8PermissionConsistency(BaseRule):
    rule_id = "R8_PERMISSION_CONSISTENCY"
    rule_name = "权限声明一致性"
    cwe = "CWE-863"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        manifest = parse_manifest(skill.path)
        if manifest is None:
            return findings  # R7 已经报了缺失 Manifest

        text = skill.skill_md

        # 遍历每条权限类型
        for perm_type, checks in CODE_PERMISSION_MAP.items():
            # 检查代码中是否有该权限的使用
            code_uses = []
            for pattern, desc in checks:
                if re.search(pattern, text, re.IGNORECASE):
                    code_uses.append(desc)

            if not code_uses:
                continue

            # 获取 Manifest 声明
            manifest_perm = self._get_manifest_perm(manifest.permissions, perm_type)

            # 如果 Manifest 声明为 none → 越权
            if manifest_perm is False:
                findings.append(
                    self._make_finding(
                        severity="L4",
                        location="manifest.yaml + SKILL.md",
                        matched=f"Manifest 声明 {perm_type}: none，但代码中存在: {', '.join(code_uses)}",
                        description=f"代码中使用 {perm_type} 权限，但 Manifest 声明为 none",
                        remediation=f"在 manifest.yaml 中声明 {perm_type} 权限为允许范围",
                    )
                )
            elif manifest_perm is None:
                # Manifest 未声明该权限
                findings.append(
                    self._make_finding(
                        severity="L3",
                        location="manifest.yaml",
                        matched=f"未声明 {perm_type} 权限，但代码使用: {', '.join(code_uses)}",
                        description=f"代码中使用 {perm_type} 操作，但 Manifest 未声明该权限",
                        remediation=f"在 manifest.yaml 的 permissions 中声明 {perm_type}",
                    )
                )

        return findings

    def _get_manifest_perm(self, permissions: dict, perm_type: str) -> bool | None:
        """检查 Manifest 中某权限的声明状态。

        Returns:
            True  — 允许
            False — 明确禁止 (none)
            None  — 未声明
        """
        if perm_type not in permissions:
            return None

        value = str(permissions[perm_type]).lower().strip()

        if value == "none":
            return False  # 明确禁止
        if value in ("all", "read", "write", "whitelist"):
            return True  # 允许

        return None

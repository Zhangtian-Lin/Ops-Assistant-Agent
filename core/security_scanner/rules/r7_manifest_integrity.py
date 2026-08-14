"""R7: Manifest 完整性检查"""

from .base import BaseRule
from ..models import Skill, Finding
from ..parser import parse_manifest


REQUIRED_SECURITY_FIELDS = ["permissions", "sandbox_policy"]
RECOMMENDED_FIELDS = ["version", "author", "resources", "depends_on"]


class R7ManifestIntegrity(BaseRule):
    rule_id = "R7_MANIFEST_INTEGRITY"
    rule_name = "Manifest 完整性"
    cwe = "CWE-1104"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []

        manifest = parse_manifest(skill.path)

        # 完全无 Manifest
        if manifest is None:
            findings.append(
                self._make_finding(
                    severity="L3",
                    location="<missing>",
                    matched="Skill 目录中未找到 manifest.yaml / manifest.json",
                    description="Skill 缺少结构化 Manifest 声明",
                    remediation="在 Skill 目录下创建 manifest.yaml，声明权限、沙箱策略、依赖关系",
                )
            )
            return findings

        # 检查关键安全字段
        for field in REQUIRED_SECURITY_FIELDS:
            value = getattr(manifest, field, None)
            if not value:
                findings.append(
                    self._make_finding(
                        severity="L3",
                        location="manifest.yaml",
                        matched=f"缺失字段: {field}",
                        description=f"Manifest 缺少关键安全字段: {field}",
                        remediation=f"在 manifest.yaml 中声明 {field}",
                    )
                )

        # 检查推荐字段
        for field in RECOMMENDED_FIELDS:
            value = getattr(manifest, field, None)
            if value is None or value == "":
                findings.append(
                    self._make_finding(
                        severity="L2",
                        location="manifest.yaml",
                        matched=f"缺失字段: {field}",
                        description=f"Manifest 缺少推荐字段: {field}",
                        remediation=f"建议在 manifest.yaml 中声明 {field}",
                    )
                )

        return findings

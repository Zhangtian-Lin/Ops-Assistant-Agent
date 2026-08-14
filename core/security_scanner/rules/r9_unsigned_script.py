"""R9: 未签名脚本检测"""

from pathlib import Path

from .base import BaseRule
from ..models import Skill, Finding

SCRIPT_EXTENSIONS = {".py", ".sh", ".js", ".rb", ".pl", ".ps1"}
SIGNATURE_EXTENSIONS = {".sig", ".asc", ".gpg"}


class R9UnsignedScript(BaseRule):
    rule_id = "R9_UNSIGNED_SCRIPT"
    rule_name = "未签名脚本"
    cwe = "CWE-345"

    def inspect(self, skill: Skill) -> list[Finding]:
        findings: list[Finding] = []
        p = Path(skill.path)

        for file_rel in skill.files:
            file_path = p / file_rel
            ext = file_path.suffix.lower()

            if ext not in SCRIPT_EXTENSIONS:
                continue

            # 检查是否有对应签名文件
            has_signature = False
            for sig_ext in SIGNATURE_EXTENSIONS:
                sig_path = file_path.with_suffix(file_path.suffix + sig_ext)
                alt_sig_path = Path(str(file_path) + sig_ext)
                if sig_path.exists() or alt_sig_path.exists():
                    has_signature = True
                    break

            if not has_signature:
                findings.append(
                    self._make_finding(
                        severity="L4",
                        location=file_rel,
                        matched=f"脚本文件无数字签名: {file_rel}",
                        description="Skill 目录中的脚本文件缺少数字签名，无法验证完整性",
                        remediation=f"对 {file_rel} 进行签名: gpg --detach-sign {file_rel}",
                    )
                )

        return findings

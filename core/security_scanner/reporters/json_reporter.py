"""JSON 格式报告生成器"""

import json
from datetime import datetime

from ..models import ScanResult, Finding


def _finding_to_dict(f: Finding) -> dict:
    return {
        "rule_id": f.rule_id,
        "rule_name": f.rule_name,
        "severity": f.severity,
        "cwe": f.cwe,
        "location": f.location,
        "matched": f.matched,
        "description": f.description,
        "remediation": f.remediation,
    }


def generate_json(result: ScanResult) -> str:
    """生成 JSON 格式报告。

    Args:
        result: 扫描结果

    Returns:
        JSON 字符串
    """
    severity_rank = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}

    report = {
        "meta": {
            "scanner": "AI Security Skill Scanner",
            "version": "1.0.0",
            "timestamp": datetime.now().isoformat(),
        },
        "skill": {
            "path": result.skill.path,
            "name": result.skill.name,
            "file_count": len(result.skill.files),
        },
        "verdict": result.verdict,
        "max_severity": result.max_severity,
        "summary": result.summary,
        "finding_count": len(result.findings),
        "findings_by_severity": {
            level: len([f for f in result.findings if f.severity == level])
            for level in ["L0", "L1", "L2", "L3", "L4", "L5"]
        },
        "findings": [
            _finding_to_dict(f)
            for f in sorted(
                result.findings,
                key=lambda x: severity_rank.get(x.severity, 0),
                reverse=True,
            )
        ],
    }

    return json.dumps(report, indent=2, ensure_ascii=False)

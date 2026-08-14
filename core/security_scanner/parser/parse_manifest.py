"""结构化 Manifest 解析器"""

import json
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class Manifest:
    """Skill 的结构化声明"""

    def __init__(
        self,
        name: str = "",
        version: str = "0.1.0",
        author: str = "",
        permissions: dict | None = None,
        resources: list[str] | None = None,
        depends_on: list[str] | None = None,
        sandbox_policy: str = "",
        signature: str | None = None,
    ):
        self.name = name
        self.version = version
        self.author = author
        self.permissions = permissions or {}
        self.resources = resources or []
        self.depends_on = depends_on or []
        self.sandbox_policy = sandbox_policy
        self.signature = signature

    def has_security_fields(self) -> bool:
        """是否声明了关键安全字段"""
        return bool(self.permissions or self.sandbox_policy)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "permissions": self.permissions,
            "resources": self.resources,
            "depends_on": self.depends_on,
            "sandbox_policy": self.sandbox_policy,
            "signature": self.signature,
        }


def parse_manifest(skill_dir: str) -> Manifest | None:
    """解析 Skill 目录中的结构化 Manifest 文件。

    支持格式：manifest.yaml / manifest.yml / manifest.json

    Args:
        skill_dir: Skill 目录路径

    Returns:
        Manifest 对象，若无 Manifest 文件则返回 None
    """
    p = Path(skill_dir)

    # 按优先级尝试各种文件名
    candidates = ["manifest.yaml", "manifest.yml", "manifest.json"]
    manifest_path = None
    for name in candidates:
        candidate = p / name
        if candidate.exists():
            manifest_path = candidate
            break

    if manifest_path is None:
        return None

    raw = manifest_path.read_text(encoding="utf-8")

    # 解析 YAML
    if manifest_path.suffix in (".yaml", ".yml"):
        if not HAS_YAML:
            raise ImportError("需要安装 PyYAML: pip install pyyaml")
        data = yaml.safe_load(raw) or {}
    # 解析 JSON
    elif manifest_path.suffix == ".json":
        data = json.loads(raw)
    else:
        return None

    return Manifest(
        name=data.get("name", ""),
        version=str(data.get("version", "0.1.0")),
        author=data.get("author", ""),
        permissions=data.get("permissions", {}),
        resources=data.get("resources", []),
        depends_on=data.get("depends_on", []),
        sandbox_policy=data.get("sandbox_policy", ""),
        signature=data.get("signature"),
    )

"""Security-mode and SID-to-role policy loading."""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterable

import yaml

from core.identity import Principal

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = WORKSPACE_ROOT / "config"
SECURITY_MODE_FILE = CONFIG_DIR / "security_mode.yaml"
IDENTITY_POLICY_FILE = CONFIG_DIR / "identity_policy.yaml"
VALID_MODES = {"single_user_controlled", "multi_user_separation"}


@dataclass(frozen=True)
class SecurityContext:
    mode: str
    policy_version: str
    principal: Principal
    roles: FrozenSet[str]


def is_configured() -> bool:
    """Return whether both local security configuration files exist."""
    return SECURITY_MODE_FILE.exists() and IDENTITY_POLICY_FILE.exists()


def _load_yaml(path: Path) -> Dict:
    if not path.exists():
        raise RuntimeError(f"Missing required security configuration: {path.name}")
    with path.open("r", encoding="utf-8") as stream:
        value = yaml.safe_load(stream) or {}
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid security configuration: {path.name}")
    return value


def load_mode() -> Dict:
    config = _load_yaml(SECURITY_MODE_FILE)
    mode = config.get("mode")
    if mode not in VALID_MODES:
        raise RuntimeError("Security mode must be single_user_controlled or multi_user_separation")
    return {"mode": mode, "policy_version": str(config.get("policy_version", "1"))}


def roles_for(principal: Principal) -> FrozenSet[str]:
    config = _load_yaml(IDENTITY_POLICY_FILE)
    principals = config.get("principals", {})
    entry = principals.get(principal.principal_id, {}) if isinstance(principals, dict) else {}
    roles = entry.get("roles", []) if isinstance(entry, dict) else []
    if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
        raise RuntimeError("Invalid roles in identity policy")
    return frozenset(roles)


def build_context(principal: Principal) -> SecurityContext:
    mode = load_mode()
    return SecurityContext(
        mode=mode["mode"],
        policy_version=mode["policy_version"],
        principal=principal,
        roles=roles_for(principal),
    )


def require_permission(context: SecurityContext, permission: str) -> None:
    if permission not in permissions_for(context):
        raise PermissionError(f"{context.principal.principal_id} lacks {permission}")


def permissions_for(context: SecurityContext) -> FrozenSet[str]:
    """Resolve permissions from trusted SID-to-role configuration."""
    policy = _load_yaml(IDENTITY_POLICY_FILE)
    role_defs = policy.get("roles", {})
    permissions = set()
    for role in context.roles:
        entry = role_defs.get(role, {}) if isinstance(role_defs, dict) else {}
        permissions.update(entry.get("permissions", []) if isinstance(entry, dict) else [])
    return frozenset(permissions)

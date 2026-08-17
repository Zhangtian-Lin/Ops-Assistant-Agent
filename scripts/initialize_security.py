"""Create local security-mode and SID-to-role configuration files."""

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.identity import get_current_principal
from core.security_mode import CONFIG_DIR, IDENTITY_POLICY_FILE, SECURITY_MODE_FILE


ROLE_DEFINITIONS = {
    "viewer": {"permissions": ["system.read", "memory.read", "knowledge.read"]},
    "operator": {"permissions": ["system.read", "approval.create", "approval.cancel_own"]},
    "approver": {"permissions": ["approval.read_pending", "approval.approve", "approval.cancel_any"]},
    "auditor": {"permissions": ["audit.read"]},
    "admin": {"permissions": ["identity.manage", "policy.manage"]},
}


def initialize_security(
    mode: str,
    operator_sid: str | None = None,
    approver_sid: str | None = None,
    *,
    force: bool = False,
) -> str:
    """Create the local security configuration and return a status message."""
    if mode not in {"single_user_controlled", "multi_user_separation"}:
        raise ValueError("Unsupported security mode")
    if (SECURITY_MODE_FILE.exists() or IDENTITY_POLICY_FILE.exists()) and not force:
        raise FileExistsError("Security configuration already exists; use --force after reviewing its impact")

    principal = get_current_principal()
    if mode == "single_user_controlled":
        principals = {principal.principal_id: {"roles": ["viewer", "operator", "approver", "auditor"]}}
    else:
        if not operator_sid or not approver_sid:
            raise ValueError("multi_user_separation requires operator and approver SIDs")
        if operator_sid == approver_sid:
            raise ValueError("operator and approver SIDs must differ")
        principals = {
            f"windows-sid:{operator_sid}": {"roles": ["viewer", "operator"]},
            f"windows-sid:{approver_sid}": {"roles": ["viewer", "approver", "auditor"]},
        }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SECURITY_MODE_FILE.write_text(
        yaml.safe_dump({"mode": mode, "policy_version": "1"}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    IDENTITY_POLICY_FILE.write_text(
        yaml.safe_dump({"roles": ROLE_DEFINITIONS, "principals": principals}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return f"Initialized {mode} for {principal.principal_id}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize OpsAgent security mode")
    parser.add_argument("--mode", choices=["single_user_controlled", "multi_user_separation"], required=True)
    parser.add_argument("--operator-sid", help="Windows SID allowed to create high-risk requests")
    parser.add_argument("--approver-sid", help="Windows SID allowed to approve high-risk requests")
    parser.add_argument("--force", action="store_true", help="Replace existing local configuration")
    args = parser.parse_args()

    try:
        print(initialize_security(args.mode, args.operator_sid, args.approver_sid, force=args.force))
    except (ValueError, FileExistsError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

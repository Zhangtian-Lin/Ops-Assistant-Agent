"""Single source of truth for tool risk and approval requirements."""

from typing import Any, Dict, Optional


POLICY_VERSION = "1"

ACTION_POLICIES: Dict[str, Dict[str, Any]] = {
    "clear_session_history": {
        "risk": "high",
        "approval_required": True,
        "ttl_seconds": 600,
        "idempotent": False,
    },
}
def get_action_policy(action: str) -> Optional[Dict[str, Any]]:
    return ACTION_POLICIES.get(action)

"""Single source of truth for tool risk and approval requirements."""

from typing import Any, Dict, Optional


POLICY_VERSION = "1"

# Each registered tool must have an explicit policy.  Unknown tools are denied.
TOOL_POLICIES: Dict[str, Dict[str, Any]] = {
    "check_cpu": {"risk": "low", "mode": "direct"},
    "check_memory": {"risk": "low", "mode": "direct"},
    "check_disk": {"risk": "low", "mode": "direct"},
    "analyze_disk_distribution": {"risk": "low", "mode": "direct"},
    "check_service": {"risk": "low", "mode": "direct"},
    "check_network": {"risk": "low", "mode": "direct"},
    "check_system": {"risk": "low", "mode": "direct"},
    "audit_skill": {"risk": "low", "mode": "direct"},
    "search_files": {"risk": "low", "mode": "direct"},
    "query_memory": {"risk": "low", "mode": "direct"},
    "query_knowledge": {"risk": "low", "mode": "direct"},
    "list_approvals": {"risk": "low", "mode": "direct"},
    "approve_request_tool": {"risk": "medium", "mode": "approval_control"},
    "cancel_request_tool": {"risk": "medium", "mode": "approval_control"},
    "clear_memory": {
        "risk": "high",
        "mode": "request_approval",
        "action": "clear_session_history",
    },
}

ACTION_POLICIES: Dict[str, Dict[str, Any]] = {
    "clear_session_history": {
        "risk": "high",
        "approval_required": True,
        "ttl_seconds": 600,
        "idempotent": False,
    },
}


def get_tool_policy(tool_name: str) -> Optional[Dict[str, Any]]:
    return TOOL_POLICIES.get(tool_name)


def get_action_policy(action: str) -> Optional[Dict[str, Any]]:
    return ACTION_POLICIES.get(action)

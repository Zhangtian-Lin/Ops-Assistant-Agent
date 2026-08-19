"""工具工程的稳定数据契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple


class ToolErrorCode(str, Enum):
    UNKNOWN = "TOOL_UNKNOWN"
    ARG_SCHEMA_INVALID = "ARG_SCHEMA_INVALID"
    ARG_SECURITY_REJECTED = "ARG_SECURITY_REJECTED"
    POLICY_DENIED = "POLICY_DENIED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TIMEOUT = "TOOL_TIMEOUT"
    EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    RESULT_SCHEMA_INVALID = "RESULT_SCHEMA_INVALID"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: Callable[..., Any]
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    risk: str
    execution_mode: str
    required_permissions: Tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    action: Optional[str] = None
    argument_validator: Optional[Callable[[Dict[str, Any]], Tuple[bool, str, Dict[str, Any]]]] = None


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    actor_permissions: Tuple[str, ...] = ()
    trace_id: str = ""


@dataclass
class ToolResult:
    status: str
    tool: str
    data: Any = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    duration_ms: float = 0.0
    policy_decision: str = ""
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}

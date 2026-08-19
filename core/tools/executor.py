"""所有工具请求必须经过的受控执行入口。"""

from __future__ import annotations

import queue
import threading
import time
from typing import Any, Dict

from .models import ToolErrorCode, ToolRequest, ToolResult
from .registry import ToolRegistry
from .schema import validate_schema


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def execute(self, request: ToolRequest) -> ToolResult:
        started = time.perf_counter()
        definition = self.registry.get(request.tool)
        if definition is None:
            return self._result(request, started, "unknown_tool", ToolErrorCode.UNKNOWN, "deny")

        schema_error = validate_schema(request.arguments, definition.input_schema)
        if schema_error:
            return self._result(request, started, "invalid_arguments", ToolErrorCode.ARG_SCHEMA_INVALID, "deny", schema_error)

        clean_args: Dict[str, Any] = dict(request.arguments)
        if definition.argument_validator is not None:
            try:
                valid, message, clean_args = definition.argument_validator(clean_args)
            except Exception:
                return self._result(request, started, "invalid_arguments", ToolErrorCode.ARG_SECURITY_REJECTED, "deny", "argument security validation failed")
            if not valid:
                return self._result(request, started, "invalid_arguments", ToolErrorCode.ARG_SECURITY_REJECTED, "deny", message)

        missing = set(definition.required_permissions) - set(request.actor_permissions)
        if missing:
            return self._result(request, started, "permission_denied", ToolErrorCode.PERMISSION_DENIED, "deny", "required permission is missing")

        if definition.execution_mode not in {"direct", "request_approval", "approval_control"}:
            return self._result(request, started, "policy_denied", ToolErrorCode.POLICY_DENIED, "deny")

        decision = "request_approval" if definition.execution_mode == "request_approval" else "allow"
        outcome: queue.Queue = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                outcome.put((True, definition.handler(**clean_args)))
            except BaseException as exc:  # converted at the trust boundary; details are not exposed
                outcome.put((False, exc))

        worker = threading.Thread(target=invoke, name=f"tool-{definition.name}", daemon=True)
        worker.start()
        worker.join(definition.timeout_seconds)
        if worker.is_alive():
            return self._result(request, started, "timeout", ToolErrorCode.TIMEOUT, decision, "tool exceeded its time limit")

        succeeded, value = outcome.get_nowait()
        if not succeeded:
            return self._result(request, started, "execution_error", ToolErrorCode.EXECUTION_FAILED, decision, "tool execution failed")
        output_error = validate_schema(value, definition.output_schema)
        if output_error:
            return self._result(request, started, "invalid_result", ToolErrorCode.RESULT_SCHEMA_INVALID, decision, "tool returned an invalid result")
        return ToolResult(
            status="success",
            tool=request.tool,
            data=value,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            policy_decision=decision,
            trace_id=request.trace_id,
        )

    @staticmethod
    def _result(
        request: ToolRequest,
        started: float,
        status: str,
        code: ToolErrorCode,
        decision: str,
        message: str | None = None,
    ) -> ToolResult:
        return ToolResult(
            status=status,
            tool=request.tool,
            error_code=code.value,
            message=message,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            policy_decision=decision,
            trace_id=request.trace_id,
        )

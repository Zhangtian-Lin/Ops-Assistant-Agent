"""Explicit single-agent runtime state; this is orchestration, not authorization."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.audit import new_trace_id, sanitize_text

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
TRACE_FILE = WORKSPACE_ROOT / "data" / "runtime" / "task_traces.jsonl"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class TaskState:
    trace_id: str
    input_hash: str
    input_preview: str
    stage: str = "created"
    route_source: Optional[str] = None
    intent: Dict[str, Any] = field(default_factory=dict)
    tool: Optional[str] = None
    policy_decision: Optional[str] = None
    outcome: Optional[str] = None
    error_code: Optional[str] = None
    duration_ms: float = 0.0
    events: List[Dict[str, Any]] = field(default_factory=list)
    _started: float = field(default_factory=time.perf_counter, repr=False)

    @classmethod
    def create(cls, user_input: str) -> "TaskState":
        state = cls(
            trace_id=new_trace_id(),
            input_hash=hashlib.sha256(user_input.encode("utf-8")).hexdigest(),
            input_preview=sanitize_text(user_input, max_length=120),
        )
        state.transition("created")
        return state

    def transition(self, stage: str, **details: Any) -> None:
        self.stage = stage
        self.events.append({"timestamp": _timestamp(), "stage": stage, "details": details})

    def finish(self, outcome: str, error_code: Optional[str] = None) -> None:
        self.outcome = outcome
        self.error_code = error_code
        self.duration_ms = round((time.perf_counter() - self._started) * 1000, 2)
        self.transition("completed", outcome=outcome, error_code=error_code, duration_ms=self.duration_ms)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.pop("_started", None)
        return payload


class AgentRuntime:
    """Coordinates one request without changing the executor's policy authority."""

    def __init__(self, router: Callable[..., Dict[str, Any]], executor: Callable[[str, Dict[str, Any], str], Dict[str, Any]], session_logger: Callable[[str, Dict[str, Any], Dict[str, Any]], None], trace_file: Path = TRACE_FILE):
        self._router = router
        self._executor = executor
        self._session_logger = session_logger
        self._trace_file = trace_file
        self.last_task: Optional[TaskState] = None

    def handle(self, user_input: str) -> Dict[str, Any]:
        state = TaskState.create(user_input)
        self.last_task = state
        capture: Dict[str, Any] = {}
        try:
            task = self._router(user_input, capture=capture)
            state.route_source = capture.get("source", "unknown")
            state.intent = capture.get("intent", {})
            state.tool = task.get("tool")
            state.transition("routed", source=state.route_source, tool=state.tool)

            if state.tool == "none":
                state.policy_decision = "deny"
                state.transition("policy_rejected", reason="no_eligible_registered_tool")
                response = {"status": "no_tool", "message": task.get("message", "没有匹配到工具"), "trace_id": state.trace_id}
                state.finish("rejected")
            else:
                state.transition("policy_evaluating", tool=state.tool)
                response = self._executor(state.tool, task.get("args", {}), state.trace_id)
                state.policy_decision = response.get("policy_decision")
                state.transition("tool_completed", tool=state.tool, status=response.get("status"), policy_decision=state.policy_decision)
                state.finish("succeeded" if response.get("status") == "success" else "failed", response.get("error_code"))
            self._session_logger(user_input, task, response)
            return response
        except Exception:
            state.transition("runtime_error", error_class="internal")
            state.finish("failed", "RUNTIME_INTERNAL_ERROR")
            response = {"status": "runtime_error", "message": "请求运行时发生内部错误", "trace_id": state.trace_id}
            self._session_logger(user_input, {"tool": "none", "args": {}}, response)
            return response
        finally:
            self._persist(state)

    def _persist(self, state: TaskState) -> None:
        """Best-effort local trace persistence; failures must not change a task result."""
        try:
            self._trace_file.parent.mkdir(parents=True, exist_ok=True)
            with self._trace_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(state.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

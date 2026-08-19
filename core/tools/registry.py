"""拒绝未知或不完整定义的工具注册表。"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

from .models import ToolDefinition


class ToolRegistrationError(ValueError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: Dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        self._validate(definition)
        if definition.name in self._definitions:
            raise ToolRegistrationError(f"duplicate tool: {definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._definitions.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def definitions(self) -> Iterable[ToolDefinition]:
        return tuple(self._definitions.values())

    @staticmethod
    def _validate(definition: ToolDefinition) -> None:
        if not definition.name or not callable(definition.handler):
            raise ToolRegistrationError("tool name and callable handler are required")
        if definition.risk not in {"low", "medium", "high"}:
            raise ToolRegistrationError(f"invalid risk for {definition.name}")
        if definition.execution_mode not in {"direct", "request_approval", "approval_control"}:
            raise ToolRegistrationError(f"invalid execution mode for {definition.name}")
        if definition.risk == "high" and definition.execution_mode == "direct":
            raise ToolRegistrationError(f"high-risk tool cannot execute directly: {definition.name}")
        if not isinstance(definition.input_schema, dict) or not isinstance(definition.output_schema, dict):
            raise ToolRegistrationError(f"schemas are required for {definition.name}")
        if not 0.1 <= definition.timeout_seconds <= 120:
            raise ToolRegistrationError(f"invalid timeout for {definition.name}")
        if definition.execution_mode == "request_approval" and not definition.action:
            raise ToolRegistrationError(f"approval action is required for {definition.name}")

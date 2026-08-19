"""项目内置工具目录：处理函数、Schema、风险和权限的唯一组合点。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from .models import ToolDefinition
from .registry import ToolRegistry


OBJECT_RESULT = {"type": "object"}
EMPTY_INPUT = {"type": "object", "properties": {}, "additionalProperties": False}


def _object_schema(properties: Dict[str, Any], required: tuple[str, ...] = ()) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def build_tool_registry(
    handlers: Mapping[str, Callable[..., Any]],
    validators: Optional[Mapping[str, Callable]] = None,
) -> ToolRegistry:
    validators = validators or {}
    path_input = _object_schema({"path": {"type": "string", "minLength": 1, "maxLength": 260}}, ("path",))
    query_input = _object_schema({"query": {"type": "string", "maxLength": 500}}, ("query",))
    specs = (
        ("check_cpu", "检查 CPU 使用率", EMPTY_INPUT, "low", "direct", ("system.read",), 5, None),
        ("check_memory", "检查内存使用情况", EMPTY_INPUT, "low", "direct", ("system.read",), 5, None),
        ("check_disk", "检查指定磁盘空间", path_input, "low", "direct", ("system.read",), 8, None),
        ("analyze_disk_distribution", "分析磁盘空间分布", path_input, "low", "direct", ("system.read",), 20, None),
        ("check_service", "检查白名单服务状态", _object_schema({"service_name": {"type": "string", "minLength": 1, "maxLength": 64}}, ("service_name",)), "low", "direct", ("system.read",), 8, None),
        ("check_network", "执行受网络策略约束的诊断", query_input, "low", "direct", ("system.read",), 12, None),
        ("check_system", "执行 Windows 系统诊断", _object_schema({"category": {"type": "string", "minLength": 1, "maxLength": 64}}, ("category",)), "low", "direct", ("system.read",), 30, None),
        ("audit_skill", "扫描本地 Skill 安全风险", path_input, "low", "direct", ("audit.read",), 30, None),
        ("search_files", "在受控范围搜索文件", query_input, "low", "direct", ("system.read",), 15, None),
        ("query_memory", "检索会话记忆", query_input, "low", "direct", ("memory.read",), 10, None),
        ("query_knowledge", "检索本地知识库", query_input, "low", "direct", ("knowledge.read",), 15, None),
        ("clear_memory", "申请清空会话记忆", EMPTY_INPUT, "high", "request_approval", ("approval.create",), 5, "clear_session_history"),
        ("list_approvals", "列出当前待审批请求", EMPTY_INPUT, "low", "direct", ("approval.read_pending",), 5, None),
        ("approve_request_tool", "批准指定审批请求", _object_schema({"request_id": {"type": "string", "pattern": r"^apr-[A-Za-z0-9_-]{16,}$"}, "confirmation": {"type": "string", "maxLength": 200}, "request_number": {"type": "integer", "minimum": 1}}, ("request_id",)), "medium", "approval_control", ("approval.approve",), 10, None),
        ("cancel_request_tool", "取消指定审批请求", _object_schema({"request_id": {"type": "string", "pattern": r"^apr-[A-Za-z0-9_-]{16,}$"}, "request_number": {"type": "integer", "minimum": 1}}, ("request_id",)), "medium", "approval_control", ("approval.cancel_own",), 10, None),
    )
    registry = ToolRegistry()
    for name, description, input_schema, risk, mode, permissions, timeout, action in specs:
        if name not in handlers:
            raise KeyError(f"missing handler for {name}")
        registry.register(ToolDefinition(
            name=name,
            description=description,
            handler=handlers[name],
            input_schema=input_schema,
            output_schema=OBJECT_RESULT,
            risk=risk,
            execution_mode=mode,
            required_permissions=permissions,
            timeout_seconds=timeout,
            action=action,
            argument_validator=validators.get(name),
        ))
    return registry

"""Authorization boundary for high-risk operations over a Windows Named Pipe."""

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core import approvals, memory
from core.identity import Principal
from core.named_pipe import DEFAULT_PIPE_NAME, NamedPipeClient, NamedPipeServer, PipeError, receive_json, send_json
from core.security_mode import SecurityContext, build_context, require_permission


class BrokerError(RuntimeError):
    pass


def _context_for_sid(sid: str) -> SecurityContext:
    principal = Principal(
        principal_id=f"windows-sid:{sid}",
        display_name=sid,
        authn_method="windows_named_pipe",
    )
    return build_context(principal)


def _execute_action(action: str, details: Dict[str, Any]) -> Dict[str, Any]:
    if action == "clear_session_history":
        return memory.perform_clear_session_history()
    raise BrokerError("No executor registered for approved action")


class ApprovalBroker:
    def dispatch(self, sid: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        context = _context_for_sid(sid)
        method = payload.get("method")
        if method == "whoami":
            return {
                "ok": True,
                "principal_id": context.principal.principal_id,
                "roles": sorted(context.roles),
                "mode": context.mode,
                "policy_version": context.policy_version,
            }
        if method == "create":
            return self._create(context, payload)
        if method == "list":
            return self._list(context)
        if method == "approve":
            return self._approve(context, payload)
        if method == "cancel":
            return self._cancel(context, payload)
        raise BrokerError("Unsupported Broker method")

    def _create(self, context: SecurityContext, payload: Dict[str, Any]) -> Dict[str, Any]:
        require_permission(context, "approval.create")
        if payload.get("action") != "clear_session_history":
            raise BrokerError("Unsupported approval action")
        result = approvals.create_request(
            "clear_session_history",
            {
                "requester": context.principal.principal_id,
                "security_mode": context.mode,
                "policy_version": context.policy_version,
            },
            requester_id=context.principal.principal_id,
        )
        return {"ok": result.get("status") == "pending", "result": result}

    def _list(self, context: SecurityContext) -> Dict[str, Any]:
        requests = approvals.list_requests(status="pending")
        if "approver" in context.roles or "auditor" in context.roles:
            return {"ok": True, "requests": requests}
        require_permission(context, "approval.create")
        own = [item for item in requests if item["requester_id"] == context.principal.principal_id]
        return {"ok": True, "requests": own}

    def _approve(self, context: SecurityContext, payload: Dict[str, Any]) -> Dict[str, Any]:
        require_permission(context, "approval.approve")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            raise BrokerError("Invalid request ID")
        request = approvals.get_request(request_id)
        if not request:
            return {"ok": False, "error": "not_found"}
        if request["details"].get("security_mode") != context.mode:
            return {"ok": False, "error": "security_mode_changed"}
        if context.mode == "multi_user_separation":
            if request["requester_id"] == context.principal.principal_id:
                return {"ok": False, "error": "separation_of_duties_violation"}
        else:
            confirmation = payload.get("confirmation")
            if confirmation != f"APPROVE {request_id}":
                return {"ok": False, "error": "confirmation_required"}
        approved = approvals.approve_request(request_id, context.principal.principal_id)
        if approved.get("status") != "approved":
            return {"ok": False, "result": approved}
        claimed = approvals.claim_execution(request_id, executor_id="OpsAgentBroker")
        if claimed.get("status") != "executing":
            return {"ok": False, "result": claimed}
        try:
            execution = _execute_action(request["action"], request["details"])
        except Exception as exc:
            completed = approvals.complete_execution(
                request_id, {"error": "Broker executor failed"}, error_code=type(exc).__name__
            )
        else:
            completed = approvals.complete_execution(request_id, execution)
        return {"ok": completed.get("status") == "executed", "result": completed}

    def _cancel(self, context: SecurityContext, payload: Dict[str, Any]) -> Dict[str, Any]:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str):
            raise BrokerError("Invalid request ID")
        request = approvals.get_request(request_id)
        if not request:
            return {"ok": False, "error": "not_found"}
        if request["requester_id"] == context.principal.principal_id:
            require_permission(context, "approval.cancel_own")
        else:
            require_permission(context, "approval.cancel_any")
        return {"ok": True, "result": approvals.cancel_request(request_id, context.principal.principal_id)}


def serve_forever(pipe_name: str = DEFAULT_PIPE_NAME, on_ready: Optional[Callable[[], None]] = None) -> None:
    server = NamedPipeServer(pipe_name)
    if on_ready:
        on_ready()
    broker = ApprovalBroker()
    while True:
        handle = server.accept()
        try:
            try:
                payload = receive_json(handle)
                # Windows permits client-token impersonation after the first request is read.
                # The payload is not trusted for identity or roles.
                from core.named_pipe import get_client_sid
                response = broker.dispatch(get_client_sid(handle), payload)
            except (BrokerError, PermissionError, PipeError) as exc:
                response = {"ok": False, "error": str(exc)}
            except Exception:
                response = {"ok": False, "error": "internal_broker_error"}
            send_json(handle, response)
        finally:
            from core.named_pipe import _close
            _close(handle)


class BrokerClient:
    def __init__(self, pipe_name: str = DEFAULT_PIPE_NAME):
        self._pipe = NamedPipeClient(pipe_name)

    def call(self, method: str, **payload: Any) -> Dict[str, Any]:
        try:
            return self._pipe.request({"method": method, **payload})
        except PipeError as exc:
            return {"ok": False, "error": str(exc)}

"""Structured, redacted audit events and Windows Event Log delivery.

The SQLite outbox is the durable source of truth.  Windows Event Log is a
delivery target: a temporary Event Log failure must never erase the security
event that describes an approval transition.
"""

import ctypes
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = WORKSPACE_ROOT / "data" / "runtime"
AUDIT_KEY_PATH = RUNTIME_DIR / "audit_hmac.key"
EVENT_SOURCE = "OpsAgent Broker"
EVENT_TYPE_INFORMATION = 0x0004
EVENT_TYPE_WARNING = 0x0002
EVENT_TYPE_ERROR = 0x0001
TRACE_ID_RE = re.compile(r"^trc-[A-Za-z0-9_-]{16,80}$")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_trace_id() -> str:
    return f"trc-{secrets.token_urlsafe(18)}"


def valid_trace_id(value: Any) -> bool:
    return isinstance(value, str) and bool(TRACE_ID_RE.fullmatch(value))


def sanitize_text(value: Any, max_length: int = 160) -> str:
    """Return a small display-safe preview; never use this for authorization."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    # User profiles often reveal a person's account name; keep only a generic marker.
    text = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s]+", r"<USER_PROFILE>", text)
    return text[:max_length]


def _audit_key() -> bytes:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return AUDIT_KEY_PATH.read_bytes()
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        # x mode prevents silently replacing an existing key.
        try:
            with AUDIT_KEY_PATH.open("xb") as handle:
                handle.write(key)
            return key
        except FileExistsError:
            return AUDIT_KEY_PATH.read_bytes()


def actor_ref(actor_id: Optional[str]) -> Optional[str]:
    if not actor_id:
        return None
    digest = hmac.new(_audit_key(), actor_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"actor-hmac:{digest[:20]}"


def build_event(
    *,
    trace_id: str,
    event_name: str,
    outcome: str,
    severity: str = "information",
    request_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a stable event envelope with only explicitly allowed details."""
    return {
        "event_version": 1,
        "event_id": f"aud-{secrets.token_urlsafe(18)}",
        "timestamp": utc_now(),
        "component": "broker",
        "event_name": event_name,
        "severity": severity,
        "outcome": outcome,
        "trace_id": trace_id,
        "request_id": request_id,
        "actor_ref": actor_ref(actor_id),
        "fields": fields or {},
    }


class WindowsEventLogWriter:
    """Small ctypes-based writer; the source must be installed by an admin first."""

    def write(self, event: Dict[str, Any]) -> None:
        if os.name != "nt":
            raise OSError("Windows Event Log is only available on Windows")
        advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi32.RegisterEventSourceW.restype = ctypes.c_void_p
        handle = advapi32.RegisterEventSourceW(None, EVENT_SOURCE)
        if not handle:
            raise OSError(ctypes.get_last_error(), "RegisterEventSourceW failed")
        try:
            payload = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            strings = (ctypes.c_wchar_p * 1)(payload)
            event_type = {
                "information": EVENT_TYPE_INFORMATION,
                "warning": EVENT_TYPE_WARNING,
                "error": EVENT_TYPE_ERROR,
            }.get(event.get("severity"), EVENT_TYPE_INFORMATION)
            if not advapi32.ReportEventW(handle, event_type, 0, 1000, None, 1, 0, strings, None):
                raise OSError(ctypes.get_last_error(), "ReportEventW failed")
        finally:
            advapi32.DeregisterEventSource(handle)

"""Durable approval state machine backed by a local SQLite database."""

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.action_policy import POLICY_VERSION, get_action_policy
from core.audit import build_event, new_trace_id, valid_trace_id

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = WORKSPACE_ROOT / "data" / "runtime"
DB_PATH = RUNTIME_DIR / "approvals.db"
LEGACY_FILE = WORKSPACE_ROOT / "data" / "memory" / "pending_approvals.json"
TERMINAL_STATES = {"executed", "failed", "cancelled", "expired"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _details_hash(details_json: str) -> str:
    return hashlib.sha256(details_json.encode("utf-8")).hexdigest()


@contextmanager
def _connect():
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _record_event(
    conn: sqlite3.Connection,
    request_id: str,
    event_type: str,
    actor_id: Optional[str],
    previous_status: Optional[str],
    new_status: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> None:
    trace_id = trace_id if valid_trace_id(trace_id) else new_trace_id()
    event_id = f"evt-{secrets.token_urlsafe(18)}"
    timestamp = _iso()
    conn.execute(
        """
        INSERT INTO approval_audit_events (
            event_id, request_id, event_type, actor_id, timestamp,
            previous_status, new_status, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            request_id,
            event_type,
            actor_id,
            timestamp,
            previous_status,
            new_status,
            _canonical_json({**(metadata or {}), "trace_id": trace_id}),
        ),
    )
    event = build_event(
        trace_id=trace_id,
        event_name=f"approval.{event_type}",
        outcome=new_status or "recorded",
        severity="error" if new_status == "failed" else "information",
        request_id=request_id,
        actor_id=actor_id,
        fields={"previous_status": previous_status, "new_status": new_status, "audit_event_id": event_id},
    )
    conn.execute(
        "INSERT INTO audit_outbox (outbox_id, event_json, created_at) VALUES (?, ?, ?)",
        (event["event_id"], _canonical_json(event), timestamp),
    )


def _row_to_request(row: sqlite3.Row) -> Dict[str, Any]:
    result = dict(row)
    result["details"] = json.loads(result.pop("details_json"))
    result.pop("details_hash", None)
    if result.get("result_json"):
        result["result"] = json.loads(result["result_json"])
    result.pop("result_json", None)
    return result


def _has_valid_details_snapshot(row: sqlite3.Row) -> bool:
    return secrets.compare_digest(_details_hash(row["details_json"]), row["details_hash"])


def _fail_integrity_check(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    previous_status = row["status"]
    conn.execute(
        """
        UPDATE approval_requests
        SET status = 'failed', completed_at = ?, error_code = 'details_integrity_check_failed',
            version = version + 1
        WHERE request_id = ?
        """,
        (_iso(), row["request_id"]),
    )
    _record_event(
        conn,
        row["request_id"],
        "failed",
        "system",
        previous_status,
        "failed",
        {"error_code": "details_integrity_check_failed"},
    )
    return {"status": "integrity_error", "current_status": "failed"}


def _expire_pending(conn: sqlite3.Connection) -> None:
    expired = conn.execute(
        """
        SELECT request_id FROM approval_requests
        WHERE status = 'pending' AND expires_at <= ?
        """,
        (_iso(),),
    ).fetchall()
    for row in expired:
        conn.execute(
            "UPDATE approval_requests SET status = 'expired', completed_at = ?, version = version + 1 WHERE request_id = ?",
            (_iso(), row["request_id"]),
        )
        _record_event(conn, row["request_id"], "expired", "system", "pending", "expired")


def initialize() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_requests (
                request_id TEXT PRIMARY KEY,
                action TEXT NOT NULL,
                details_json TEXT NOT NULL,
                details_hash TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                status TEXT NOT NULL,
                requester_id TEXT NOT NULL,
                requester_session_id TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                approved_by TEXT,
                approved_at TEXT,
                execution_started_at TEXT,
                completed_at TEXT,
                result_json TEXT,
                error_code TEXT,
                policy_version TEXT NOT NULL,
                idempotency_key TEXT,
                version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approval_audit_events (
                event_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_id TEXT,
                timestamp TEXT NOT NULL,
                previous_status TEXT,
                new_status TEXT,
                metadata_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_outbox (
                outbox_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_approval_events_request ON approval_audit_events(request_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_outbox_pending ON audit_outbox(delivered_at, created_at)")
        _migrate_legacy_requests(conn)
        _expire_pending(conn)


def _migrate_legacy_requests(conn: sqlite3.Connection) -> None:
    if not LEGACY_FILE.exists():
        return
    try:
        legacy = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(legacy, list):
        return

    for item in legacy:
        if not isinstance(item, dict):
            continue
        request_id = item.get("request_id")
        action = item.get("action")
        policy = get_action_policy(action) if isinstance(action, str) else None
        if not isinstance(request_id, str) or not policy:
            continue
        if conn.execute("SELECT 1 FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone():
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        details_json = _canonical_json(details)
        created_at = item.get("created_at") if isinstance(item.get("created_at"), str) else _iso()
        status = item.get("status") if item.get("status") in {"pending", "approved"} else "expired"
        # Old requests had neither a secure ID nor expiry.  They are imported as expired.
        status = "expired"
        conn.execute(
            """
            INSERT INTO approval_requests (
                request_id, action, details_json, details_hash, risk_level, status,
                requester_id, created_at, expires_at, completed_at, policy_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                action,
                details_json,
                _details_hash(details_json),
                policy["risk"],
                status,
                str(details.get("requester", "legacy")),
                created_at,
                _iso(),
                _iso(),
                POLICY_VERSION,
            ),
        )
        _record_event(conn, request_id, "legacy_imported", "system", None, status)


def create_request(
    action: str,
    details: Dict[str, Any],
    requester_id: str,
    requester_session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    initialize()
    policy = get_action_policy(action)
    if not policy or not policy.get("approval_required"):
        return {"status": "unsupported_action"}
    details_json = _canonical_json(details)
    request_id = f"apr-{secrets.token_urlsafe(24)}"
    created = _now()
    expires = created + timedelta(seconds=int(policy["ttl_seconds"]))
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO approval_requests (
                request_id, action, details_json, details_hash, risk_level, status,
                requester_id, requester_session_id, created_at, expires_at, policy_version
            ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                action,
                details_json,
                _details_hash(details_json),
                policy["risk"],
                requester_id,
                requester_session_id,
                _iso(created),
                _iso(expires),
                POLICY_VERSION,
            ),
        )
        _record_event(conn, request_id, "created", requester_id, None, "pending", trace_id=trace_id)
        row = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
    return {"status": "pending", "request": _row_to_request(row)}


def list_requests(status: Optional[str] = "pending") -> List[Dict[str, Any]]:
    initialize()
    with _connect() as conn:
        _expire_pending(conn)
        if status:
            rows = conn.execute(
                "SELECT * FROM approval_requests WHERE status = ? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM approval_requests ORDER BY created_at DESC").fetchall()
    return [_row_to_request(row) for row in rows]


def get_request(request_id: str) -> Optional[Dict[str, Any]]:
    initialize()
    with _connect() as conn:
        _expire_pending(conn)
        row = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
    return _row_to_request(row) if row else None


def approve_request(request_id: str, approver_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    initialize()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _expire_pending(conn)
        row = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not row:
            return {"status": "not_found"}
        if row["status"] != "pending":
            return {"status": "invalid_state", "current_status": row["status"]}
        if not _has_valid_details_snapshot(row):
            return _fail_integrity_check(conn, row)
        conn.execute(
            """
            UPDATE approval_requests
            SET status = 'approved', approved_by = ?, approved_at = ?, version = version + 1
            WHERE request_id = ? AND status = 'pending'
            """,
            (approver_id, _iso(), request_id),
        )
        _record_event(conn, request_id, "approved", approver_id, "pending", "approved", trace_id=trace_id)
        updated = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
    return {"status": "approved", "request": _row_to_request(updated)}


def claim_execution(request_id: str, executor_id: str = "agent", trace_id: Optional[str] = None) -> Dict[str, Any]:
    initialize()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not row:
            return {"status": "not_found"}
        if row["status"] != "approved":
            return {"status": "invalid_state", "current_status": row["status"]}
        if not _has_valid_details_snapshot(row):
            return _fail_integrity_check(conn, row)
        conn.execute(
            """
            UPDATE approval_requests
            SET status = 'executing', execution_started_at = ?, version = version + 1
            WHERE request_id = ? AND status = 'approved'
            """,
            (_iso(), request_id),
        )
        _record_event(conn, request_id, "executing", executor_id, "approved", "executing", trace_id=trace_id)
        updated = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
    return {"status": "executing", "request": _row_to_request(updated)}


def complete_execution(request_id: str, result: Dict[str, Any], error_code: Optional[str] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
    initialize()
    final_status = "failed" if error_code else "executed"
    result_json = _canonical_json(result)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not row:
            return {"status": "not_found"}
        if row["status"] != "executing":
            return {"status": "invalid_state", "current_status": row["status"]}
        conn.execute(
            """
            UPDATE approval_requests
            SET status = ?, completed_at = ?, result_json = ?, error_code = ?, version = version + 1
            WHERE request_id = ? AND status = 'executing'
            """,
            (final_status, _iso(), result_json, error_code, request_id),
        )
        _record_event(conn, request_id, final_status, "agent", "executing", final_status, {"error_code": error_code}, trace_id)
        updated = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
    return {"status": final_status, "request": _row_to_request(updated)}


def cancel_request(request_id: str, actor_id: str, trace_id: Optional[str] = None) -> Dict[str, Any]:
    initialize()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _expire_pending(conn)
        row = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
        if not row:
            return {"status": "not_found"}
        if row["status"] not in {"pending", "approved"}:
            return {"status": "invalid_state", "current_status": row["status"]}
        conn.execute(
            "UPDATE approval_requests SET status = 'cancelled', completed_at = ?, version = version + 1 WHERE request_id = ?",
            (_iso(), request_id),
        )
        _record_event(conn, request_id, "cancelled", actor_id, row["status"], "cancelled", trace_id=trace_id)
        updated = conn.execute("SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)).fetchone()
    return {"status": "cancelled", "request": _row_to_request(updated)}


def list_audit_events(request_id: str) -> List[Dict[str, Any]]:
    initialize()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM approval_audit_events WHERE request_id = ? ORDER BY timestamp", (request_id,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        result.append(item)
    return result


def queue_broker_event(trace_id: str, event_name: str, outcome: str, actor_id: Optional[str] = None, fields: Optional[Dict[str, Any]] = None, severity: str = "information") -> None:
    """Persist a non-transition Broker event for later Event Log delivery."""
    initialize()
    event = build_event(trace_id=trace_id, event_name=event_name, outcome=outcome, actor_id=actor_id, fields=fields, severity=severity)
    with _connect() as conn:
        conn.execute("INSERT INTO audit_outbox (outbox_id, event_json, created_at) VALUES (?, ?, ?)", (event["event_id"], _canonical_json(event), event["timestamp"]))


def deliver_audit_outbox(writer: Any, limit: int = 100) -> Dict[str, int]:
    """Deliver pending events in order. A failure leaves the event pending for retry."""
    initialize()
    delivered = failed = 0
    with _connect() as conn:
        rows = conn.execute("SELECT outbox_id, event_json FROM audit_outbox WHERE delivered_at IS NULL ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        for row in rows:
            try:
                writer.write(json.loads(row["event_json"]))
            except Exception as exc:
                conn.execute("UPDATE audit_outbox SET attempts = attempts + 1, last_error = ? WHERE outbox_id = ?", (type(exc).__name__, row["outbox_id"]))
                failed += 1
            else:
                conn.execute("UPDATE audit_outbox SET delivered_at = ?, attempts = attempts + 1, last_error = NULL WHERE outbox_id = ?", (_iso(), row["outbox_id"]))
                delivered += 1
    return {"delivered": delivered, "failed": failed}


def list_outbox_events(delivered: Optional[bool] = None) -> List[Dict[str, Any]]:
    initialize()
    with _connect() as conn:
        query = "SELECT * FROM audit_outbox"
        params: tuple = ()
        if delivered is not None:
            query += " WHERE delivered_at IS " + ("NOT NULL" if delivered else "NULL")
        rows = conn.execute(query + " ORDER BY created_at", params).fetchall()
    return [{**dict(row), "event": json.loads(row["event_json"])} for row in rows]

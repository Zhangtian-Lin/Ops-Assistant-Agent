"""Skill 发现、隔离扫描、人工确认和安装的显式状态机。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from core.security_scanner.scan_engine import scan_skill


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = WORKSPACE_ROOT / "data" / "skills"
STAGING_ROOT = SKILL_ROOT / "staging"
INSTALLED_ROOT = SKILL_ROOT / "installed"
STATE_FILE = SKILL_ROOT / "lifecycle.json"
MAX_FILES = 200
MAX_TOTAL_BYTES = 10 * 1024 * 1024


class SkillLifecycleError(RuntimeError):
    pass


class SkillLifecycle:
    _lock = threading.RLock()

    def discover(self, source: str) -> Dict[str, Any]:
        source_path = Path(source).resolve(strict=True)
        if not source_path.is_dir() or not (source_path / "SKILL.md").is_file():
            raise SkillLifecycleError("candidate must be a directory containing SKILL.md")
        files = [path for path in source_path.rglob("*") if path.is_file()]
        if any(path.is_symlink() for path in source_path.rglob("*")):
            raise SkillLifecycleError("symbolic links are not accepted in candidate skills")
        if len(files) > MAX_FILES or sum(path.stat().st_size for path in files) > MAX_TOTAL_BYTES:
            raise SkillLifecycleError("candidate exceeds staging limits")

        candidate_id = f"skill-{uuid.uuid4().hex}"
        destination = STAGING_ROOT / candidate_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_path, destination)
        digest = self._digest(destination)
        record = {
            "candidate_id": candidate_id,
            "name": self._safe_name(source_path.name),
            "state": "discovered",
            "digest": digest,
            "created_at": self._now(),
            "scan": None,
            "confirmed_at": None,
            "installed_at": None,
        }
        self._save_record(record)
        return self._public(record)

    def scan(self, candidate_id: str) -> Dict[str, Any]:
        record = self._record(candidate_id)
        if record["state"] not in {"discovered", "scanned"}:
            raise SkillLifecycleError("candidate is not in a scannable state")
        candidate = self._candidate_path(candidate_id)
        if self._digest(candidate) != record["digest"]:
            raise SkillLifecycleError("candidate changed after discovery")
        result = scan_skill(str(candidate))
        record["scan"] = {
            "verdict": result.verdict,
            "max_severity": result.max_severity,
            "finding_count": len(result.findings),
            "summary": result.summary,
        }
        record["state"] = "scanned"
        self._save_record(record)
        public = self._public(record)
        public["confirmation_phrase"] = f"INSTALL {candidate_id} {record['digest'][:12]}"
        return public

    def confirm(self, candidate_id: str, confirmation: str) -> Dict[str, Any]:
        record = self._record(candidate_id)
        if record["state"] != "scanned" or not record.get("scan"):
            raise SkillLifecycleError("candidate must be scanned before confirmation")
        if record["scan"]["verdict"] != "PASS":
            raise SkillLifecycleError("blocked candidate cannot be confirmed")
        expected = f"INSTALL {candidate_id} {record['digest'][:12]}"
        if confirmation != expected:
            raise SkillLifecycleError("explicit confirmation phrase does not match")
        record["state"] = "confirmed"
        record["confirmed_at"] = self._now()
        self._save_record(record)
        return self._public(record)

    def install(self, candidate_id: str) -> Dict[str, Any]:
        record = self._record(candidate_id)
        if record["state"] != "confirmed":
            raise SkillLifecycleError("candidate requires explicit confirmation before installation")
        candidate = self._candidate_path(candidate_id)
        if self._digest(candidate) != record["digest"]:
            raise SkillLifecycleError("candidate changed after confirmation")
        destination = INSTALLED_ROOT / record["name"]
        if destination.exists():
            raise SkillLifecycleError("an installed skill with this name already exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        shutil.copytree(candidate, temporary)
        os.replace(temporary, destination)
        record["state"] = "installed"
        record["installed_at"] = self._now()
        self._save_record(record)
        return self._public(record)

    def _record(self, candidate_id: str) -> Dict[str, Any]:
        if not re.fullmatch(r"skill-[0-9a-f]{32}", candidate_id):
            raise SkillLifecycleError("invalid candidate id")
        state = self._load_state()
        record = state.get("candidates", {}).get(candidate_id)
        if not record:
            raise SkillLifecycleError("candidate not found")
        return record

    @staticmethod
    def _safe_name(name: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]", "-", name).strip(".-")
        if not value:
            raise SkillLifecycleError("candidate name is invalid")
        return value[:80]

    @staticmethod
    def _candidate_path(candidate_id: str) -> Path:
        path = (STAGING_ROOT / candidate_id).resolve()
        if path.parent != STAGING_ROOT.resolve() or not path.is_dir():
            raise SkillLifecycleError("invalid staging path")
        return path

    @staticmethod
    def _digest(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    @classmethod
    def _load_state(cls) -> Dict[str, Any]:
        if not STATE_FILE.exists():
            return {"version": 1, "candidates": {}}
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or not isinstance(value.get("candidates"), dict):
            raise SkillLifecycleError("invalid lifecycle state")
        return value

    @classmethod
    def _save_record(cls, record: Dict[str, Any]) -> None:
        with cls._lock:
            state = cls._load_state()
            state["candidates"][record["candidate_id"]] = record
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            temporary = STATE_FILE.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, STATE_FILE)

    @staticmethod
    def _public(record: Dict[str, Any]) -> Dict[str, Any]:
        return {key: record.get(key) for key in ("candidate_id", "name", "state", "digest", "scan", "created_at", "confirmed_at", "installed_at")}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

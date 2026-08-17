"""Run the local OpsAgent Broker. Install as a Windows service separately for production."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.broker import serve_forever

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
READY_FILE = WORKSPACE_ROOT / "data" / "runtime" / "broker.ready"


def mark_ready() -> None:
    READY_FILE.parent.mkdir(parents=True, exist_ok=True)
    READY_FILE.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")


if __name__ == "__main__":
    READY_FILE.unlink(missing_ok=True)
    try:
        serve_forever(on_ready=mark_ready)
    finally:
        READY_FILE.unlink(missing_ok=True)

"""Local Windows identity helpers used by the approval broker."""

import csv
import io
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str
    authn_method: str


def _run_whoami(*args: str) -> str:
    return subprocess.check_output(["whoami", *args], text=True, encoding="utf-8", errors="replace")


def get_current_principal() -> Principal:
    """Return the OS-authenticated local principal; never accept a caller-supplied identity."""
    if os.name == "nt":
        output = _run_whoami("/user", "/fo", "csv", "/nh").strip()
        rows = list(csv.reader(io.StringIO(output)))
        if not rows or len(rows[0]) < 2 or not rows[0][1].startswith("S-"):
            raise RuntimeError("Unable to resolve the current Windows SID")
        return Principal(
            principal_id=f"windows-sid:{rows[0][1]}",
            display_name=rows[0][0],
            authn_method="windows_logon",
        )

    uid = os.getuid()
    return Principal(
        principal_id=f"unix-uid:{uid}",
        display_name=os.getenv("USER", str(uid)),
        authn_method="os_session",
    )

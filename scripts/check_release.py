"""Fail a release if its tag/version metadata or required verification evidence is missing."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="Expected release tag, e.g. v0.4.0")
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if args.tag != f"v{version}":
        print("release tag must match VERSION")
        return 1
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"[{version}]" not in changelog:
        print("CHANGELOG does not contain the current VERSION")
        return 1
    verification = json.loads((ROOT / "reports" / "latest_verification.json").read_text(encoding="utf-8"))
    if not verification.get("summary", {}).get("successful"):
        print("verification evidence is not successful")
        return 1
    print(f"release gate passed for {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

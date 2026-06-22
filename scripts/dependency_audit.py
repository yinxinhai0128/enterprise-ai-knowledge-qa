"""Audit the hash-locked runtime graph and enforce expiring risk acceptance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_policy(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("accepted"), list):
        raise ValueError("invalid vulnerability acceptance policy")
    return data["accepted"]


def _is_accepted(
    vulnerability: dict[str, object], package: str, version: str, policy: list[dict[str, object]]
) -> tuple[bool, str]:
    vuln_id = str(vulnerability["id"])
    today = date.today()
    for item in policy:
        if item.get("id") != vuln_id or item.get("package") != package:
            continue
        if version not in item.get("versions", []):
            return False, "accepted version does not match"
        expires = date.fromisoformat(str(item["expires_on"]))
        if expires < today:
            return False, f"acceptance expired on {expires.isoformat()}"
        if not item.get("owner") or not item.get("reason") or not item.get("controls"):
            return False, "acceptance is missing owner, reason, or controls"
        return True, f"accepted until {expires.isoformat()} by {item['owner']}"
    return False, "not present in accepted-vulnerabilities.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=ROOT / "requirements.lock")
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "security" / "accepted-vulnerabilities.json"
    )
    args = parser.parse_args()

    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "-r",
        str(args.lock),
        "--require-hashes",
        "--format",
        "json",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        print(completed.stderr.strip() or "pip-audit produced no JSON report", file=sys.stderr)
        return 2

    policy = _load_policy(args.policy)
    unaccepted: list[str] = []
    accepted: list[str] = []
    findings = 0
    for dependency in report.get("dependencies", []):
        package = str(dependency["name"]).lower()
        version = str(dependency["version"])
        for vulnerability in dependency.get("vulns", []):
            findings += 1
            ok, detail = _is_accepted(vulnerability, package, version, policy)
            message = f"{package}=={version} {vulnerability['id']}: {detail}"
            (accepted if ok else unaccepted).append(message)

    for message in accepted:
        print(f"ACCEPTED: {message}")
    for message in unaccepted:
        print(f"UNACCEPTED: {message}", file=sys.stderr)
    print(
        f"dependency_audit: dependencies={len(report.get('dependencies', []))} "
        f"findings={findings} accepted={len(accepted)} unaccepted={len(unaccepted)}"
    )
    return 1 if unaccepted else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail on Critical/High container CVEs without a scoped, unexpired acceptance."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SEVERITY_RE = re.compile(r"Severity\s*:\s*(CRITICAL|HIGH)", re.IGNORECASE)
PACKAGE_RE = re.compile(r"Package\s*:\s*pkg:[^/]+/(?:[^/]+/)?([^@\s]+)@([^?\s]+)", re.IGNORECASE)


def parse_finding(result: dict[str, object]) -> dict[str, str]:
    message_data = result.get("message")
    message = str(message_data.get("text", "")) if isinstance(message_data, dict) else ""
    severity_match = SEVERITY_RE.search(message)
    package_match = PACKAGE_RE.search(message)
    if not severity_match or not package_match or not result.get("ruleId"):
        raise ValueError(f"unrecognized Docker Scout SARIF result: {result.get('ruleId')}")
    return {
        "id": str(result["ruleId"]),
        "severity": severity_match.group(1).upper(),
        "package": package_match.group(1).lower(),
        "version": unquote(package_match.group(2)),
    }


def _load_policy(path: Path) -> list[dict[str, object]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("accepted"), list):
        raise ValueError("invalid vulnerability acceptance policy")
    return data["accepted"]


def _acceptance(finding: dict[str, str], policy: list[dict[str, object]]) -> str | None:
    for item in policy:
        if item.get("id") != finding["id"] or item.get("package") != finding["package"]:
            continue
        versions = item.get("versions")
        if not isinstance(versions, list) or finding["version"] not in versions:
            return None
        expires = date.fromisoformat(str(item["expires_on"]))
        if expires < date.today():
            return None
        if not item.get("owner") or not item.get("reason") or not item.get("controls"):
            return None
        return f"accepted until {expires.isoformat()} by {item['owner']}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="local://enterprise-kb-api:stage8")
    parser.add_argument(
        "--policy", type=Path, default=ROOT / "security" / "accepted-vulnerabilities.json"
    )
    args = parser.parse_args()

    completed = subprocess.run(
        [
            "docker",
            "scout",
            "cves",
            "--format",
            "sarif",
            "--only-severity",
            "critical,high",
            args.image,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        print(completed.stderr.strip() or "Docker Scout failed", file=sys.stderr)
        return 2
    try:
        report = json.loads(completed.stdout)
        results = report["runs"][0].get("results", [])
        findings = [parse_finding(result) for result in results]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
        print(f"invalid Docker Scout SARIF: {exc}", file=sys.stderr)
        return 2

    policy = _load_policy(args.policy)
    unaccepted: list[str] = []
    accepted: list[str] = []
    for finding in findings:
        detail = _acceptance(finding, policy)
        message = (
            f"{finding['severity']} {finding['id']} "
            f"{finding['package']}=={finding['version']}"
        )
        if detail:
            accepted.append(f"{message}: {detail}")
        else:
            unaccepted.append(message)

    for message in accepted:
        print(f"ACCEPTED: {message}")
    for message in unaccepted:
        print(f"UNACCEPTED: {message}", file=sys.stderr)
    print(
        f"container_audit: findings={len(findings)} "
        f"accepted={len(accepted)} unaccepted={len(unaccepted)}"
    )
    return 1 if unaccepted else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Scan version-controlled source without ever printing candidate secret values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "github-token": re.compile(r"\bgh[oprsu]_[A-Za-z0-9_]{30,}\b"),
    "provider-key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
}
ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|jwt[_-]?secret|password)"
    r"\s*[=:]\s*[\"']?([^\s\"'#]{8,})"
)
SAFE_MARKERS = (
    "${",
    "example",
    "dummy",
    "test-",
    "not-used",
    "change-me",
    "replace-me",
    "your-",
    "settings.",
)


def _tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return [ROOT / item.decode() for item in completed.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[tuple[str, int, str]] = []
    for path in _tracked_files():
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(ROOT).as_posix()
        for line_number, line_text in enumerate(text.splitlines(), start=1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line_text):
                    findings.append((relative, line_number, name))
            assignment = ASSIGNMENT.search(line_text)
            if assignment:
                value = assignment.group(1).lower()
                if not any(marker in value for marker in SAFE_MARKERS):
                    findings.append((relative, line_number, "credential-assignment"))

    for filename, line_number, kind in findings:
        print(f"SECRET_CANDIDATE: {filename}:{line_number} ({kind})")
    print(f"secret_scan: candidates={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependencies_are_exact_and_hash_locked():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    active = [line.strip() for line in requirements.splitlines() if line.strip() and not line.startswith("#")]
    assert active
    assert all("==" in line and ">=" not in line for line in active)

    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    assert "--hash=sha256:" in lock
    assert "chromadb==1.5.9" in lock


def test_dockerfile_pins_image_and_preserves_immutable_source():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    first_from = next(line for line in dockerfile.splitlines() if line.startswith("FROM "))
    assert re.fullmatch(r"FROM python:3\.12\.12-slim-bookworm@sha256:[0-9a-f]{64}", first_from)
    assert "COPY . ." not in dockerfile
    assert "COPY --chown=root:root app /app/app" in dockerfile
    assert "chown -R appuser:appuser /app" not in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "--require-hashes" in dockerfile


def test_compose_has_no_chroma_server_and_enforces_runtime_controls():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert not any("chroma" in name.lower() for name in services)
    for service in services.values():
        assert service["user"] == "10001:10001"
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["pids_limit"] > 0
        assert service["mem_limit"]
        assert service["cpus"] > 0
        assert any(item.startswith("/tmp:") for item in service["tmpfs"])


def test_docker_context_excludes_sensitive_and_development_inputs():
    ignored = set((ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines())
    required = {".env", ".git", ".claude", "tests", "requirements-dev.txt", "backups/", "storage/", "chroma_db/"}
    assert required <= ignored


def test_vulnerability_acceptance_is_scoped_and_not_expired():
    policy = json.loads(
        (ROOT / "security" / "accepted-vulnerabilities.json").read_text(encoding="utf-8")
    )
    accepted = policy["accepted"]
    assert len(accepted) == 1
    item = accepted[0]
    assert item["id"] == "CVE-2026-45829"
    assert item["package"] == "chromadb"
    assert item["versions"] == ["1.5.9"]
    assert date.fromisoformat(item["expires_on"]) >= date.today()
    assert item["owner"] and item["reason"] and item["controls"]

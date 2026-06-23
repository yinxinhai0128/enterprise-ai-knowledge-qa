from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_runs_required_gates_without_real_secrets():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for command in (
        "python -m pip install --require-hashes -r requirements.lock",
        "python -m pip install -r requirements-dev.txt",
        "python -m ruff check app tests scripts",
        "python -m mypy",
        "python scripts/secret_scan.py",
        "python -m pytest -q",
        "python scripts/check_test_cleanup.py",
        "python scripts/dependency_audit.py",
        "docker/build-push-action@v6",
    ):
        assert command in workflow
    assert "test-key-not-used" in workflow
    assert 'LANGCHAIN_TRACING_V2: "false"' in workflow
    assert "${{ secrets." not in workflow
    assert "Copy-Item .env" not in workflow


def test_development_tools_are_exactly_pinned():
    requirements = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    active = [
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.startswith(("#", "-r"))
    ]
    assert active
    assert all("==" in requirement for requirement in active)
    assert any(requirement.startswith("ruff==") for requirement in active)
    assert any(requirement.startswith("mypy==") for requirement in active)

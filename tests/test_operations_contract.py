from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_alerts_have_thresholds_severity_and_runbook():
    policy = yaml.safe_load((ROOT / "config" / "alerts.yml").read_text(encoding="utf-8"))
    assert policy["schema_version"] == 1
    names = {alert["name"] for alert in policy["alerts"]}
    assert {
        "APIReadinessFailed",
        "HTTPP95LatencyHigh",
        "RefusalRateHigh",
        "HumanReviewRateHigh",
        "IngestFailureRateHigh",
        "IngestQueueBacklogHigh",
        "ModelTimeoutBurst",
        "ModelRetryBurst",
        "MetricsDatabaseUnavailable",
        "DailyModelCostHigh",
    } <= names
    for alert in policy["alerts"]:
        assert alert["severity"] in {"warning", "critical"}
        assert alert["runbook"]
        assert alert.get("query") or alert.get("condition")


def test_runbook_covers_each_failure_and_safe_restore():
    runbook = (ROOT / "docs" / "OPERATIONS_RUNBOOK.md").read_text(encoding="utf-8")
    for required in (
        "/health/live",
        "/health/ready",
        "/metrics",
        "READINESS_DATABASE_UNAVAILABLE",
        "READINESS_VECTORSTORE_UNAVAILABLE",
        "READINESS_WORKER_LEASE_STALE",
        "MODEL_TIMEOUT",
        "backup_restore.py backup",
        "backup_restore.py restore",
        "total_issues=0",
        "绝不原地覆盖",
    ):
        assert required in runbook


def test_compose_uses_readiness_not_liveness():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "/health/ready" in compose
    assert "/health/ready" in dockerfile
    assert "condition: service_healthy" in compose

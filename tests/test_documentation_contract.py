"""阶段 11：文档必须与实际路由、默认配置和安全边界一致。"""
from __future__ import annotations

import os
from pathlib import Path

import jwt
import pytest
from dotenv import dotenv_values

from app.config import Settings
from app.main import create_app
from scripts.create_dev_token import create_dev_token

ROOT = Path(__file__).resolve().parents[1]


def test_deployment_document_lists_every_runtime_api_path():
    documented = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    paths = create_app().openapi()["paths"]
    for path in paths:
        assert f"`{path}`" in documented, path


def test_documented_model_defaults_match_settings_and_env_example():
    example = dotenv_values(ROOT / ".env.example")
    fields = Settings.model_fields
    assert example["LLM_MODEL"] == fields["llm_model"].default == "qwen3.6-plus"
    assert example["EMBED_MODEL"] == fields["embed_model"].default == "text-embedding-v3"
    assert example["APP_ENV"] == fields["app_env"].default == "development"
    assert example["APP_HOST"] == fields["app_host"].default == "127.0.0.1"
    assert int(example["APP_PORT"] or 0) == fields["app_port"].default == 8000
    known_fields = {name.upper() for name in fields}
    assert set(example) <= known_fields


def test_readme_avoids_unverified_production_claims_and_links_required_docs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for forbidden in ("开箱即用", "零运维", "可平滑切换", "已生产可用", "企业级生产可用"):
        assert forbidden not in readme
    for required in (
        "生产候选整改中",
        "docs/DEPLOYMENT.md",
        "docs/THREAT_MODEL.md",
        "docs/OPERATIONS_RUNBOOK.md",
        "docs/LANGSMITH_DATA_GOVERNANCE.md",
        "scripts\\create_dev_token.py",
    ):
        assert required in readme


def test_deployment_has_three_profiles_migrations_rotation_and_limits():
    deployment = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    for required in (
        "development",
        "test",
        "production",
        "Token 获取",
        "数据库迁移与升级",
        "备份恢复",
        "Key 轮换",
        "LangSmith 数据治理",
        "已知限制与容量边界",
        "MALWARE_SCAN_REQUIRED=true",
    ):
        assert required in deployment


def test_threat_model_covers_required_threats_and_boundaries():
    threat_model = (ROOT / "docs" / "THREAT_MODEL.md").read_text(encoding="utf-8")
    for required in (
        "flowchart",
        "信任边界",
        "匿名访问",
        "越权与跨租户",
        "提示词注入",
        "恶意文件",
        "数据外传",
        "费用与资源攻击",
        "剩余风险",
    ):
        assert required in threat_model


def test_development_token_contains_required_claims(monkeypatch):
    secret = "test-only-development-secret-at-least-32-characters"
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_JWT_SECRET", secret)
    monkeypatch.setenv("AUTH_JWT_ISSUER", "test-idp")
    monkeypatch.setenv("AUTH_JWT_AUDIENCE", "test-audience")
    token = create_dev_token(
        user_id="local-user",
        tenant_id="local-tenant",
        roles=["user"],
        ttl_seconds=300,
    )
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer="test-idp",
        audience="test-audience",
    )
    assert claims["sub"] == "local-user"
    assert claims["tenant_id"] == "local-tenant"
    assert claims["roles"] == ["user"]


def test_development_token_refuses_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "AUTH_JWT_SECRET", "test-only-development-secret-at-least-32-characters"
    )
    with pytest.raises(RuntimeError, match="disabled"):
        create_dev_token(
            user_id="local-user",
            tenant_id="local-tenant",
            roles=["user"],
            ttl_seconds=300,
        )
    assert os.environ["APP_ENV"] == "production"

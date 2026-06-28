"""使用量报表与反馈统计端点的测试。"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_usage_report_empty(client: AsyncClient, auth_headers):
    admin_hdrs = auth_headers(roles=("admin",))
    resp = await client.get("/admin/reports/usage?days=7", headers=admin_hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["refused_rate"] == 0.0
    assert len(data["daily"]) == 7
    assert data["top_users"] == []
    assert data["top_docs"] == []


@pytest.mark.asyncio
async def test_usage_report_invalid_days(client: AsyncClient, auth_headers):
    admin_hdrs = auth_headers(roles=("admin",))
    resp = await client.get("/admin/reports/usage?days=0", headers=admin_hdrs)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_usage_report_non_admin(client: AsyncClient, auth_headers):
    qa_hdrs = auth_headers(roles=("user",))
    resp = await client.get("/admin/reports/usage?days=7", headers=qa_hdrs)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_feedback_stats_empty(client: AsyncClient, auth_headers):
    admin_hdrs = auth_headers(roles=("admin",))
    resp = await client.get("/admin/feedback-stats", headers=admin_hdrs)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rated"] == 0
    assert data["approval_rate"] == 0.0
    assert data["recent_negatives"] == []

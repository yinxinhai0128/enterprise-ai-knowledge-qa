"""Agent 层公共入口（使用惰性导出，避免工具与中间件循环导入）。"""
from __future__ import annotations

from typing import Any

__all__ = ["build_agent", "EnterpriseAuditMiddleware", "EnterpriseContext"]


def __getattr__(name: str) -> Any:
    if name == "build_agent":
        from app.agent.agent import build_agent

        return build_agent
    if name in {"EnterpriseAuditMiddleware", "EnterpriseContext"}:
        from app.agent.middleware import EnterpriseAuditMiddleware, EnterpriseContext

        return {
            "EnterpriseAuditMiddleware": EnterpriseAuditMiddleware,
            "EnterpriseContext": EnterpriseContext,
        }[name]
    raise AttributeError(name)

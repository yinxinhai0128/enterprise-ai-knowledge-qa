"""Agent 运行时可信上下文。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnterpriseContext:
    """只能由已认证 API 层构造，不接受模型或请求体覆盖。"""

    session_id: str
    tenant_id: str
    user_id: str

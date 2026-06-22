"""Agent 运行时可信上下文。"""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class EnterpriseContext:
    """只能由已认证 API 层构造，不接受模型或请求体覆盖。"""

    session_id: str
    tenant_id: str
    user_id: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"user"}))
    audit_id: int | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    started_monotonic: float = field(default_factory=perf_counter)

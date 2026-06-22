"""请求速率/并发保护与持久化每日模型预算。"""
from __future__ import annotations

import asyncio
import math
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select, text

from app.config import settings
from app.core.auth import AuthContext, require_admin, require_user
from app.core.database import AsyncSessionLocal
from app.models.usage_daily import UsageDaily


class RequestLimiter:
    """单进程滑动窗口 + 并发计数；持久化全局预算由数据库负责。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._windows: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._active: dict[tuple[str, str], int] = defaultdict(int)

    @asynccontextmanager
    async def limit(
        self,
        *,
        scope: str,
        identity: str,
        per_minute: int,
        max_concurrency: int,
    ) -> AsyncIterator[None]:
        key = (scope, identity)
        now = monotonic()
        async with self._lock:
            window = self._windows[key]
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= per_minute:
                retry_after = max(1, math.ceil(60 - (now - window[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="请求过于频繁，请稍后重试",
                    headers={"Retry-After": str(retry_after)},
                )
            if self._active[key] >= max_concurrency:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="并发请求过多，请稍后重试",
                    headers={"Retry-After": "1"},
                )
            window.append(now)
            self._active[key] += 1
        try:
            yield
        finally:
            async with self._lock:
                self._active[key] = max(0, self._active[key] - 1)

    async def reset(self) -> None:
        """仅供测试隔离。"""
        async with self._lock:
            self._windows.clear()
            self._active.clear()


request_limiter = RequestLimiter()


def _identity(auth: AuthContext) -> str:
    return f"{auth.tenant_id}:{auth.user_id}"


async def _qa_guard(
    auth: Annotated[AuthContext, Depends(require_user)],
) -> AsyncIterator[AuthContext]:
    async with request_limiter.limit(
        scope="qa",
        identity=_identity(auth),
        per_minute=settings.qa_rate_limit_per_minute,
        max_concurrency=settings.qa_max_concurrency,
    ):
        yield auth


async def _upload_guard(
    auth: Annotated[AuthContext, Depends(require_user)],
) -> AsyncIterator[AuthContext]:
    async with request_limiter.limit(
        scope="upload",
        identity=_identity(auth),
        per_minute=settings.upload_rate_limit_per_minute,
        max_concurrency=settings.upload_max_concurrency,
    ):
        yield auth


async def _admin_guard(
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> AsyncIterator[AuthContext]:
    async with request_limiter.limit(
        scope="admin",
        identity=_identity(auth),
        per_minute=settings.admin_rate_limit_per_minute,
        max_concurrency=settings.admin_max_concurrency,
    ):
        yield auth


QAAuth = Annotated[AuthContext, Depends(_qa_guard)]
UploadAuth = Annotated[AuthContext, Depends(_upload_guard)]
LimitedAdminAuth = Annotated[AuthContext, Depends(_admin_guard)]


@dataclass(frozen=True, slots=True)
class UsageReservation:
    model_calls: int
    tokens: int


def estimate_request_token_budget(question: str) -> UsageReservation:
    """按最坏输出上限预留预算；无 usage metadata 时也不会低估费用。"""
    input_estimate = max(1, len(question.encode("utf-8")) // 2)
    calls = settings.max_model_calls_per_request
    tokens = input_estimate + calls * settings.llm_max_output_tokens
    return UsageReservation(model_calls=calls, tokens=tokens)


async def reserve_daily_model_budget(
    auth: AuthContext,
    question: str,
) -> UsageReservation:
    """在调用模型前原子预留用户/租户每日调用次数与 Token 预算。"""
    reservation = estimate_request_token_budget(question)
    usage_date = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as db:
        if db.bind is not None and db.bind.dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
        row = (
            await db.execute(
                select(UsageDaily).where(
                    UsageDaily.usage_date == usage_date,
                    UsageDaily.tenant_id == auth.tenant_id,
                    UsageDaily.user_id == auth.user_id,
                )
            )
        ).scalar_one_or_none()
        tenant_totals = (
            await db.execute(
                select(
                    func.coalesce(func.sum(UsageDaily.model_calls_reserved), 0),
                    func.coalesce(func.sum(UsageDaily.tokens_reserved), 0),
                ).where(
                    UsageDaily.usage_date == usage_date,
                    UsageDaily.tenant_id == auth.tenant_id,
                )
            )
        ).one()
        user_calls = int(row.model_calls_reserved) if row else 0
        user_tokens = int(row.tokens_reserved) if row else 0
        tenant_calls, tenant_tokens = map(int, tenant_totals)

        if (
            user_calls + reservation.model_calls > settings.daily_user_model_calls
            or tenant_calls + reservation.model_calls
            > settings.daily_tenant_model_calls
            or user_tokens + reservation.tokens > settings.daily_user_token_budget
            or tenant_tokens + reservation.tokens > settings.daily_tenant_token_budget
        ):
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="今日模型调用或 Token 预算已用尽",
                headers={"Retry-After": "3600"},
            )

        if row is None:
            row = UsageDaily(
                usage_date=usage_date,
                tenant_id=auth.tenant_id,
                user_id=auth.user_id,
                model_calls_reserved=0,
                tokens_reserved=0,
            )
            db.add(row)
        row.model_calls_reserved += reservation.model_calls
        row.tokens_reserved += reservation.tokens
        await db.commit()
    return reservation

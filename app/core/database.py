"""数据库：异步引擎、会话工厂、声明基类与初始化。

统一用 SQLAlchemy 2.0 异步风格 + aiosqlite。其它模块通过
`get_session`（FastAPI 依赖）或 `AsyncSessionLocal`（后台任务）拿会话。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 异步引擎（SQLite 需要 echo=False，连接串见 settings.database_url）
engine = create_async_engine(settings.database_url, echo=False, future=True)

# 会话工厂：expire_on_commit=False 便于 commit 后仍能读对象字段
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明基类。"""


async def init_db() -> None:
    """建表（开发期用 create_all；生产应改用 Alembic 迁移）。"""
    # 导入模型以注册到 Base.metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session

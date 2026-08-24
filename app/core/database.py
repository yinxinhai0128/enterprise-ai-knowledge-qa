"""数据库：异步引擎、会话工厂、声明基类与初始化。

统一用 SQLAlchemy 2.0 异步风格 + aiosqlite。其它模块通过
`get_session`（FastAPI 依赖）或 `AsyncSessionLocal`（后台任务）拿会话。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

CURRENT_SCHEMA_REVISION = "20260704_0001"

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



def _ensure_tenant_indexes(connection: Connection) -> None:
    """建立高频租户过滤索引；语句可安全重复执行。"""
    # create_all 不会为已有表补建 ORM 的 index=True 索引，显式收敛旧库 schema。
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documents_tenant_id "
            "ON documents (tenant_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documents_uploaded_by "
            "ON documents (uploaded_by)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chat_records_tenant_id "
            "ON chat_records (tenant_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chat_records_user_id "
            "ON chat_records (user_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chat_records_audit_status "
            "ON chat_records (audit_status)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_documents_tenant_created "
            "ON documents (tenant_id, created_at)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_tenant_sha256 "
            "ON documents (tenant_id, content_sha256) "
            "WHERE content_sha256 IS NOT NULL"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_chat_tenant_user_session "
            "ON chat_records (tenant_id, user_id, session_id)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_trace_id "
            "ON chat_records (trace_id) WHERE trace_id IS NOT NULL"
        )
    )


async def init_db() -> None:
    """建表（开发期用 create_all；生产应改用 Alembic 迁移）。"""
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        # pgvector 扩展（PostgreSQL 才有效，SQLite 会跳过）
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception:
            pass
        await conn.run_sync(Base.metadata.create_all)
        # 传统租户索引（保留兼容性）
        try:
            await conn.run_sync(_ensure_tenant_indexes)
        except Exception:
            pass
        # document_chunks 向量列的 HNSW 索引（M1-B 创建该表后生效）
        try:
            await conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_doc_chunks_embed_hnsw "
                "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
                "WITH (m=16, ef_construction=64)"
            ))
        except Exception:
            pass


async def init_schema_for_runtime() -> None:
    """Initialize local schema; production only verifies Alembic state."""
    if settings.app_env == "production":
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                revision = result.scalar_one_or_none()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Production database schema is not migrated. "
                f"Expected Alembic revision {CURRENT_SCHEMA_REVISION}. "
                "Run `alembic upgrade head` before starting API/worker."
            ) from exc
        if revision != CURRENT_SCHEMA_REVISION:
            raise RuntimeError(
                "Production database schema is not migrated. "
                f"Expected Alembic revision {CURRENT_SCHEMA_REVISION}, got {revision!r}. "
                "Run `alembic upgrade head` before starting API/worker."
            )
        return
    await init_db()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session

"""数据库：异步引擎、会话工厂、声明基类与初始化。

统一用 SQLAlchemy 2.0 异步风格 + aiosqlite。其它模块通过
`get_session`（FastAPI 依赖）或 `AsyncSessionLocal`（后台任务）拿会话。
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import Connection, inspect, text
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


def _migrate_schema(connection: Connection) -> None:
    """以幂等方式补齐当前阶段需要的列并保留既有数据。"""
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    migrations = {
        "documents": (
            ("tenant_id", "VARCHAR(128) NOT NULL DEFAULT 'legacy'"),
            ("uploaded_by", "VARCHAR(128) NOT NULL DEFAULT 'legacy'"),
            ("content_sha256", "VARCHAR(64) NULL"),
        ),
        "chat_records": (
            ("tenant_id", "VARCHAR(128) NOT NULL DEFAULT 'legacy'"),
            ("user_id", "VARCHAR(128) NOT NULL DEFAULT 'legacy'"),
            ("refused", "BOOLEAN NOT NULL DEFAULT 0"),
            ("tool_used", "BOOLEAN NOT NULL DEFAULT 0"),
            ("sources", "JSON NOT NULL DEFAULT '[]'"),
            ("trace_id", "VARCHAR(64) NULL"),
            ("model", "VARCHAR(128) NULL"),
            ("input_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("total_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("latency_ms", "FLOAT NOT NULL DEFAULT 0"),
            ("audit_status", "VARCHAR(32) NOT NULL DEFAULT 'completed'"),
            ("audit_error", "TEXT NULL"),
            ("policy_category", "VARCHAR(64) NULL"),
            ("policy_rule_version", "VARCHAR(64) NULL"),
            ("feedback_rating", "VARCHAR(8) NULL"),
            ("feedback_comment", "TEXT NULL"),
        ),
    }
    for table, columns in migrations.items():
        if table not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl in columns:
            if name not in existing:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                if table == "chat_records" and name == "refused":
                    # 仅用于一次性迁移旧记录；新请求的 refused 只由真实 evidence 决定。
                    connection.execute(
                        text(
                            "UPDATE chat_records SET refused = 1 "
                            "WHERE has_source = 0 AND ("
                            "answer LIKE :m1 OR answer LIKE :m2 OR "
                            "answer LIKE :m3 OR answer LIKE :m4)"
                        ),
                        {
                            "m1": "%没有找到相关%",
                            "m2": "%未找到相关%",
                            "m3": "%知识库中没有%",
                            "m4": "%无法回答%",
                        },
                    )


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
    # 导入模型以注册到 Base.metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(_migrate_schema)
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_tenant_indexes)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话，结束自动关闭。"""
    async with AsyncSessionLocal() as session:
        yield session

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

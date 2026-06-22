"""FastAPI 入口：注册 lifespan 与 /health。

业务路由后续在 app/api/ 下拆分，再在此处 include_router。
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.api.admin import router as admin_router
from app.api.documents import router as documents_router
from app.api.qa import router as qa_router
from app.config import settings
from app.core.database import init_db


def _configure_logging() -> None:
    """配置 loguru：控制台 + 文件滚动。"""
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(
        settings.log_dir / "app_{time:YYYY-MM-DD}.log",
        level=settings.log_level,
        rotation="00:00",
        retention="14 days",
        encoding="utf-8",
        enqueue=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化资源，关闭时清理。"""
    settings.ensure_dirs()
    _configure_logging()
    logger.info("启动企业级 Agentic RAG 知识库 …")
    logger.info("LLM={} | Embed={} | Base={}", settings.llm_model, settings.embed_model, settings.dashscope_base_url)

    # 建表（开发期 create_all；生产改 Alembic）
    await init_db()
    logger.info("数据库已就绪")

    # TODO: 如需可在此预热向量库 / Agent，挂到 app.state
    yield

    logger.info("服务关闭，资源已释放。")


app = FastAPI(
    title="企业级 Agentic RAG 知识库",
    version="0.1.0",
    description="LangChain 1.3 + LangGraph 构建的可复用知识问答模板",
    lifespan=lifespan,
)


@app.get("/health", tags=["system"], summary="健康检查")
async def health() -> dict:
    """存活探针，供 Docker / 负载均衡使用。"""
    return {"status": "ok", "service": "enterprise-kb", "version": app.version}


# 业务路由
app.include_router(documents_router)
app.include_router(qa_router)
app.include_router(admin_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )

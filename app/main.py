"""FastAPI 入口：注册 lifespan 与 /health。

业务路由后续在 app/api/ 下拆分，再在此处 include_router。
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger
from starlette.requests import Request
from starlette.responses import Response

from app.api.admin import router as admin_router
from app.api.documents import router as documents_router
from app.api.qa import router as qa_router
from app.agent.agent import build_agent
from app.config import settings
from app.core.checkpointer import close_checkpointer, init_checkpointer
from app.core.database import init_db
from app.core.process_pool import shutdown_parser_pool
from app.core.tracing import (
    TracePolicyError,
    configure_langsmith,
    record_trace_decision,
    shutdown_langsmith,
)
from app.core.vectorstore import migrate_legacy_vector_metadata
from app.services.ingest_jobs import recover_stale_ingest_state
from app.services.conversations import cleanup_expired_conversations


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
    try:
        trace_decision = configure_langsmith()
    except TracePolicyError as exc:
        # 仅关闭未获批的外部追踪，不牺牲知识库核心服务可用性。
        trace_decision = exc.decision
        logger.warning("LangSmith 追踪被治理门拒绝 reason={}", trace_decision.reason)
    await record_trace_decision(trace_decision)
    await init_checkpointer()
    expired_sessions = await cleanup_expired_conversations()
    recovered = await recover_stale_ingest_state()
    migrated_vectors = await asyncio.to_thread(migrate_legacy_vector_metadata)
    logger.info(
        "数据库已就绪 | expired_sessions={} | recovered_jobs={} | repaired_documents={} | legacy_vectors_migrated={}",
        expired_sessions,
        recovered["jobs"],
        recovered["documents"],
        migrated_vectors,
    )

    # TODO: 如需可在此预热向量库 / Agent，挂到 app.state
    yield

    shutdown_parser_pool()
    build_agent.cache_clear()
    await close_checkpointer()
    shutdown_langsmith()
    logger.info("服务关闭，资源已释放。")


def create_app() -> FastAPI:
    """按运行环境创建 FastAPI 应用。"""
    is_production = settings.app_env == "production"
    application = FastAPI(
        title="企业级 Agentic RAG 知识库",
        version="0.1.0",
        description="LangChain 1.3 + LangGraph 构建的可复用知识问答模板",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )

    @application.middleware("http")
    async def add_security_headers(request: Request, call_next) -> Response:
        """为所有响应添加基础浏览器与缓存安全策略。"""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Cache-Control"] = "no-store"
        if is_production:
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        else:
            # 开发模式保留 Swagger UI 所需的 CDN 资源。
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @application.get("/health", tags=["system"], summary="健康检查")
    async def health() -> dict[str, str]:
        """最小存活探针，不暴露版本和内部组件。"""
        return {"status": "ok"}

    application.include_router(documents_router)
    application.include_router(qa_router)
    application.include_router(admin_router)
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )

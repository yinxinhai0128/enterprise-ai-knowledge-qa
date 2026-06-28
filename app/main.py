"""FastAPI 入口：生命周期、健康探针、可观测性与业务路由。

业务路由后续在 app/api/ 下拆分，再在此处 include_router。
"""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi import Request as FastAPIRequest
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response

from app.agent.agent import build_agent
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.qa import router as qa_router
from app.config import settings
from app.core.checkpointer import close_checkpointer, init_checkpointer
from app.core.database import init_db
from app.core.observability import (
    normalize_request_id,
    render_metrics,
    request_id_var,
    runtime_metrics,
    sanitize_log_record,
)
from app.core.process_pool import shutdown_parser_pool
from app.core.tracing import (
    TracePolicyError,
    configure_langsmith,
    record_trace_decision,
    shutdown_langsmith,
)
from app.core.vectorstore import migrate_legacy_vector_metadata
from app.services.conversations import cleanup_expired_conversations
from app.services.health import evaluate_readiness
from app.services.ingest_jobs import recover_stale_ingest_state

_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "ACCESS_DENIED",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "UPLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def _configure_logging() -> None:
    """配置 JSON 日志；patcher 会移除凭据与异常原文。"""
    logger.remove()
    logger.configure(patcher=sanitize_log_record)
    logger.add(
        sys.stderr,
        level=settings.log_level,
        serialize=True,
        diagnose=False,
        backtrace=False,
    )
    logger.add(
        settings.log_dir / "app_{time:YYYY-MM-DD}.log",
        level=settings.log_level,
        rotation="00:00",
        retention="14 days",
        encoding="utf-8",
        enqueue=True,
        serialize=True,
        diagnose=False,
        backtrace=False,
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

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: FastAPIRequest, exc: StarletteHTTPException
    ) -> JSONResponse:
        error_code = _ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        request_id = request_id_var.get()
        logger.bind(
            event="http_error",
            error_code=error_code,
            status_code=exc.status_code,
            method=request.method,
            path=request.url.path,
        ).warning("http_request_rejected")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": jsonable_encoder(exc.detail),
                "error_code": error_code,
                "request_id": request_id,
            },
            headers=exc.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: FastAPIRequest, exc: RequestValidationError
    ) -> JSONResponse:
        logger.bind(
            event="http_error",
            error_code="VALIDATION_ERROR",
            status_code=422,
            method=request.method,
            path=request.url.path,
        ).warning("http_request_validation_failed")
        return JSONResponse(
            status_code=422,
            content={
                "detail": jsonable_encoder(exc.errors()),
                "error_code": "VALIDATION_ERROR",
                "request_id": request_id_var.get(),
            },
        )

    @application.exception_handler(Exception)
    async def internal_error_handler(request: FastAPIRequest, exc: Exception) -> JSONResponse:
        logger.bind(
            event="http_error",
            error_code="INTERNAL_ERROR",
            status_code=500,
            method=request.method,
            path=request.url.path,
            failure_type=type(exc).__name__,
        ).error("unhandled_http_error")
        return JSONResponse(
            status_code=500,
            content={
                "detail": "服务内部错误",
                "error_code": "INTERNAL_ERROR",
                "request_id": request_id_var.get(),
            },
        )

    @application.middleware("http")
    async def observe_and_secure(request: Request, call_next) -> Response:
        """关联请求、记录低基数指标，并添加安全响应头。"""
        request_id = normalize_request_id(
            request.headers.get("X-Request-ID"), uuid4().hex
        )
        token = request_id_var.set(request_id)
        started = perf_counter()
        try:
            with logger.contextualize(request_id=request_id):
                response = await call_next(request)
        finally:
            request_id_var.reset(token)

        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        elapsed = max(0.0, perf_counter() - started)
        runtime_metrics.record_request(request.method, route_path, response.status_code, elapsed)
        logger.bind(
            event="http_request",
            request_id=request_id,
            method=request.method,
            route=route_path,
            status_code=response.status_code,
            latency_ms=round(elapsed * 1000, 3),
        ).info("http_request_complete")
        response.headers["X-Request-ID"] = request_id
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
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @application.get("/health/live", tags=["system"], summary="存活检查")
    async def health_live() -> dict[str, str]:
        """仅证明 HTTP 进程仍可响应。"""
        return {"status": "ok"}

    @application.get("/health", tags=["system"], summary="兼容存活检查", deprecated=True)
    async def health_legacy() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", tags=["system"], summary="就绪检查")
    async def health_ready() -> JSONResponse:
        ready, components = await evaluate_readiness()
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "components": components},
        )

    @application.get("/metrics", tags=["system"], summary="Prometheus 指标")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            await render_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    application.include_router(auth_router)
    application.include_router(documents_router)
    application.include_router(qa_router)
    application.include_router(admin_router)

    if not is_production:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=[
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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

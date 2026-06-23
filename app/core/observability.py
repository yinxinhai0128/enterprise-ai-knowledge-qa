"""本地可观测性：请求关联、安全日志、运行时计数与 Prometheus 文本指标。"""
from __future__ import annotations

import re
import threading
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from langchain.agents.middleware import ModelRetryMiddleware
from loguru import logger
from sqlalchemy import case, func, select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.chat_record import ChatRecord
from app.models.document import Document
from app.models.ingest_job import IngestJob

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_TOKEN_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[=:]\s*[^\s,;]+"),
)
_LATENCY_BUCKETS = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0)


def normalize_request_id(candidate: str | None, fallback: str) -> str:
    """只接受短、可打印的关联 ID，防止日志注入。"""
    return candidate if candidate and _SAFE_REQUEST_ID.fullmatch(candidate) else fallback


def redact_log_text(value: object) -> str:
    """移除已知密钥与常见凭据形态；不返回原始 Secret。"""
    text = str(value)
    known_secrets = (
        settings.dashscope_api_key,
        settings.langsmith_api_key,
        settings.auth_jwt_secret.get_secret_value(),
        settings.langsmith_redaction_secret.get_secret_value(),
    )
    for secret in known_secrets:
        if len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def sanitize_log_record(record: Any) -> None:
    """Loguru patcher：脱敏消息/extra，并仅保留异常类型。"""
    record["message"] = redact_log_text(record["message"])
    record["extra"] = {
        key: redact_log_text(value) if isinstance(value, str) else value
        for key, value in record["extra"].items()
    }
    if record["exception"] is not None:
        record["extra"]["exception_type"] = record["exception"].type.__name__
        record["extra"]["exception_module"] = record["exception"].type.__module__
        # 异常消息可能包含供应商请求内容、文件片段或凭据，只记录类型。
        record["exception"] = None


@dataclass(slots=True)
class RequestSeries:
    count: int = 0
    latency_seconds_sum: float = 0.0
    buckets: dict[float, int] = field(
        default_factory=lambda: {boundary: 0 for boundary in _LATENCY_BUCKETS}
    )


class RuntimeMetrics:
    """进程内低基数指标；持久业务指标在抓取时从数据库聚合。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, str], RequestSeries] = defaultdict(RequestSeries)
        self._model_retries = 0
        self._model_timeouts = 0
        self._collection_errors = 0

    def record_request(self, method: str, route: str, status: int, elapsed: float) -> None:
        key = (method, route, f"{status // 100}xx")
        with self._lock:
            series = self._requests[key]
            series.count += 1
            series.latency_seconds_sum += elapsed
            for boundary in _LATENCY_BUCKETS:
                if elapsed <= boundary:
                    series.buckets[boundary] += 1

    def record_model_retries(self, count: int) -> None:
        with self._lock:
            self._model_retries += max(0, count)

    def record_model_timeout(self) -> None:
        with self._lock:
            self._model_timeouts += 1

    def record_collection_error(self) -> None:
        with self._lock:
            self._collection_errors += 1

    def snapshot(self) -> tuple[dict[tuple[str, str, str], RequestSeries], int, int, int]:
        with self._lock:
            requests = {
                key: RequestSeries(value.count, value.latency_seconds_sum, dict(value.buckets))
                for key, value in self._requests.items()
            }
            return requests, self._model_retries, self._model_timeouts, self._collection_errors

    def reset(self) -> None:
        """仅供隔离测试清空进程指标。"""
        with self._lock:
            self._requests.clear()
            self._model_retries = 0
            self._model_timeouts = 0
            self._collection_errors = 0


runtime_metrics = RuntimeMetrics()


def _is_timeout(exc: BaseException) -> bool:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, TimeoutError) or "timeout" in type(current).__name__.lower():
            return True
        current = current.__cause__ or current.__context__
    return False


class ObservedModelRetryMiddleware(ModelRetryMiddleware):
    """复用 LangChain 官方重试语义，同时记录真实重试与超时次数。"""

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        failures = 0

        def observed_handler(observed_request: Any) -> Any:
            nonlocal failures
            try:
                return handler(observed_request)
            except Exception as exc:
                failures += 1
                if _is_timeout(exc):
                    runtime_metrics.record_model_timeout()
                    logger.bind(
                        event="model_timeout",
                        error_code="MODEL_TIMEOUT",
                    ).error("model_call_timeout")
                raise

        try:
            return super().wrap_model_call(request, observed_handler)
        finally:
            runtime_metrics.record_model_retries(min(failures, self.max_retries))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        failures = 0

        async def observed_handler(observed_request: Any) -> Any:
            nonlocal failures
            try:
                return await handler(observed_request)
            except Exception as exc:
                failures += 1
                if _is_timeout(exc):
                    runtime_metrics.record_model_timeout()
                    logger.bind(
                        event="model_timeout",
                        error_code="MODEL_TIMEOUT",
                    ).error("model_call_timeout")
                raise

        try:
            return await super().awrap_model_call(request, observed_handler)
        finally:
            runtime_metrics.record_model_retries(min(failures, self.max_retries))


def _labels(**labels: str) -> str:
    escaped = [
        f'{key}="{value.replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"'
        for key, value in labels.items()
    ]
    return "{" + ",".join(escaped) + "}" if escaped else ""


async def render_metrics() -> str:
    """生成不含租户、用户、问题或文件名的 Prometheus 文本。"""
    requests, model_retries, model_timeouts, collection_errors = runtime_metrics.snapshot()
    lines = [
        "# HELP enterprise_kb_http_requests_total HTTP requests by bounded route/status labels.",
        "# TYPE enterprise_kb_http_requests_total counter",
        "# HELP enterprise_kb_http_request_duration_seconds HTTP request latency histogram.",
        "# TYPE enterprise_kb_http_request_duration_seconds histogram",
    ]
    for (method, route, status_class), series in sorted(requests.items()):
        labels = _labels(method=method, route=route, status_class=status_class)
        lines.append(f"enterprise_kb_http_requests_total{labels} {series.count}")
        lines.append(f"enterprise_kb_http_request_duration_seconds_sum{labels} {series.latency_seconds_sum:.6f}")
        lines.append(f"enterprise_kb_http_request_duration_seconds_count{labels} {series.count}")
        for boundary, count in series.buckets.items():
            bucket_labels = _labels(
                method=method,
                route=route,
                status_class=status_class,
                le=str(boundary),
            )
            lines.append(f"enterprise_kb_http_request_duration_seconds_bucket{bucket_labels} {count}")
        infinite_labels = _labels(
            method=method,
            route=route,
            status_class=status_class,
            le="+Inf",
        )
        lines.append(
            f"enterprise_kb_http_request_duration_seconds_bucket{infinite_labels} {series.count}"
        )

    persistent = {
        "database_up": 1.0,
        "qa_total": 0.0,
        "qa_refused_total": 0.0,
        "qa_refused_rate": 0.0,
        "qa_human_total": 0.0,
        "qa_human_rate": 0.0,
        "model_input_tokens_total": 0.0,
        "model_output_tokens_total": 0.0,
        "model_tokens_total": 0.0,
        "model_estimated_cost": 0.0,
        "documents_total": 0.0,
        "documents_failed_total": 0.0,
        "ingest_jobs_total": 0.0,
        "ingest_jobs_failed_total": 0.0,
        "ingest_failure_rate": 0.0,
        "ingest_queue_backlog": 0.0,
        "ingest_jobs_running": 0.0,
        "ingest_retries_total": 0.0,
    }
    try:
        async with AsyncSessionLocal() as db:
            qa = (
                await db.execute(
                    select(
                        func.count(ChatRecord.id),
                        func.coalesce(func.sum(case((ChatRecord.refused.is_(True), 1), else_=0)), 0),
                        func.coalesce(func.sum(case((ChatRecord.need_human.is_(True), 1), else_=0)), 0),
                        func.coalesce(func.sum(ChatRecord.input_tokens), 0),
                        func.coalesce(func.sum(ChatRecord.output_tokens), 0),
                        func.coalesce(func.sum(ChatRecord.total_tokens), 0),
                    )
                )
            ).one()
            docs = (
                await db.execute(
                    select(
                        func.count(Document.id),
                        func.coalesce(func.sum(case((Document.status == "failed", 1), else_=0)), 0),
                    )
                )
            ).one()
            jobs = (
                await db.execute(
                    select(
                        func.count(IngestJob.id),
                        func.coalesce(func.sum(case((IngestJob.status == "failed", 1), else_=0)), 0),
                        func.coalesce(
                            func.sum(case((IngestJob.status.in_(("pending", "retry")), 1), else_=0)),
                            0,
                        ),
                        func.coalesce(func.sum(case((IngestJob.status == "running", 1), else_=0)), 0),
                        func.coalesce(
                            func.sum(case((IngestJob.attempt > 1, IngestJob.attempt - 1), else_=0)),
                            0,
                        ),
                    )
                )
            ).one()
        input_tokens, output_tokens = int(qa[3]), int(qa[4])
        qa_total, qa_refused, qa_human = int(qa[0]), int(qa[1]), int(qa[2])
        jobs_total, jobs_failed = int(jobs[0]), int(jobs[1])
        persistent.update(
            qa_total=float(qa_total),
            qa_refused_total=float(qa_refused),
            qa_refused_rate=qa_refused / qa_total if qa_total else 0.0,
            qa_human_total=float(qa_human),
            qa_human_rate=qa_human / qa_total if qa_total else 0.0,
            model_input_tokens_total=float(input_tokens),
            model_output_tokens_total=float(output_tokens),
            model_tokens_total=float(qa[5]),
            model_estimated_cost=(
                input_tokens * settings.llm_input_cost_per_million
                + output_tokens * settings.llm_output_cost_per_million
            )
            / 1_000_000,
            documents_total=float(docs[0]),
            documents_failed_total=float(docs[1]),
            ingest_jobs_total=float(jobs_total),
            ingest_jobs_failed_total=float(jobs_failed),
            ingest_failure_rate=jobs_failed / jobs_total if jobs_total else 0.0,
            ingest_queue_backlog=float(jobs[2]),
            ingest_jobs_running=float(jobs[3]),
            ingest_retries_total=float(jobs[4]),
        )
    except Exception:  # noqa: BLE001
        persistent["database_up"] = 0.0
        runtime_metrics.record_collection_error()
        logger.bind(
            event="metrics_collection_failed",
            component="sqlite",
            error_code="METRICS_DATABASE_UNAVAILABLE",
        ).error("metrics_collection_failed")

    _, _, _, collection_errors = runtime_metrics.snapshot()
    for name, value in persistent.items():
        lines.append(f"enterprise_kb_{name} {value:g}")
    lines.extend(
        (
            f"enterprise_kb_model_retries_total {model_retries}",
            f"enterprise_kb_model_timeouts_total {model_timeouts}",
            f"enterprise_kb_metrics_collection_errors_total {collection_errors}",
        )
    )
    return "\n".join(lines) + "\n"


def request_timer() -> float:
    return perf_counter()

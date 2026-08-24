"""QA 响应 Redis 精确匹配缓存（按 tenant_id + question 哈希）。

原则：
- 只缓存有来源（sources 非空）的成功响应；拒答和错误不缓存。
- 不含 session_id：同一问题跨会话复用答案。
- Redis 故障时静默降级，不影响主流程。
- TTL 可配置；qa_cache_ttl_seconds=0 禁用。
"""
from __future__ import annotations

import hashlib
import json

from loguru import logger

from app.config import settings


def _key(tenant_id: str, question: str) -> str:
    digest = hashlib.sha256(
        f"{tenant_id}:{question.strip()}".encode()
    ).hexdigest()[:32]
    return f"ekqa:qa:{digest}"


async def get_cached_qa(tenant_id: str, question: str) -> dict | None:
    """返回缓存的 AskResponse 字典，或 None（未命中/禁用/Redis 故障）。"""
    if settings.qa_cache_ttl_seconds == 0:
        return None
    try:
        from app.core.redis_client import get_redis
        r = await get_redis()
        raw = await r.get(_key(tenant_id, question))
        if raw:
            logger.debug("QA cache HIT tenant={} q={:.40s}", tenant_id, question)
            return json.loads(raw)
    except Exception:  # noqa: BLE001
        logger.warning("QA cache GET 失败，降级到无缓存路径")
    return None


async def set_cached_qa(tenant_id: str, question: str, response: dict) -> None:
    """写入缓存；Redis 故障时静默忽略。"""
    if settings.qa_cache_ttl_seconds == 0:
        return
    try:
        from app.core.redis_client import get_redis
        r = await get_redis()
        await r.setex(
            _key(tenant_id, question),
            settings.qa_cache_ttl_seconds,
            json.dumps(response, ensure_ascii=False),
        )
        logger.debug("QA cache SET tenant={} q={:.40s}", tenant_id, question)
    except Exception:  # noqa: BLE001
        logger.warning("QA cache SET 失败，继续正常响应")

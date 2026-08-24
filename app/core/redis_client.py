"""进程级异步 Redis 客户端单例。"""
from __future__ import annotations

import redis.asyncio as aioredis
from loguru import logger

from app.config import settings

_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=3.0,
            socket_connect_timeout=3.0,
            retry_on_timeout=True,
        )
    return _client


async def init_redis() -> None:
    r = await get_redis()
    pong = await r.ping()
    logger.info("Redis 已连接 url={} ping={}", settings.redis_url, pong)


async def close_redis() -> None:
    global _client
    if _client:
        await _client.aclose()
        _client = None
        logger.info("Redis 连接已关闭")

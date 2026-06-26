"""模型工厂：统一构造对话大模型与向量模型。

全部经阿里云百炼 OpenAI 兼容接口调用，参数从 `settings` 读取，
不在此处硬编码任何 Key / 地址 / 模型名。
"""
from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings


def init_llm(**overrides: Any) -> ChatOpenAI:
    """构造对话大模型（百炼，OpenAI 兼容）。

    Args:
        **overrides: 临时覆盖参数，如 temperature、max_tokens、model 等。

    Returns:
        ChatOpenAI: 可直接传入 `create_agent(model=...)` 的模型实例。
    """
    params: dict[str, Any] = dict(
        model=settings.llm_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        temperature=0.0,
        max_tokens=settings.llm_max_output_tokens,
        timeout=60,
        max_retries=2,
    )
    params.update(overrides)
    return ChatOpenAI(**params)


def init_embeddings(**overrides: Any) -> OpenAIEmbeddings:
    """构造向量模型（百炼 text-embedding-v3，OpenAI 兼容）。

    说明：百炼向量接口不兼容 OpenAI 的 tiktoken 分块逻辑，
    需关闭 `check_embedding_ctx_length`，否则可能报错。

    Args:
        **overrides: 临时覆盖参数，如 dimensions、model 等。

    Returns:
        OpenAIEmbeddings: 可直接传入 Chroma 的向量化器实例。
    """
    params: dict[str, Any] = dict(
        model=settings.embed_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
        # 百炼 text-embedding-v3 单次请求最多 10 条，必须显式设置否则默认 1000 超限报错
        chunk_size=10,
        check_embedding_ctx_length=False,
    )
    params.update(overrides)
    return OpenAIEmbeddings(**params)

"""检索工具：把 Chroma 检索包装成 Agent 可调用的 @tool。

Agentic RAG 的关键：检索是一个工具，由 Agent 自主决定何时调用，
而不是固定先检索再回答。工具的 docstring 就是给模型看的调用说明。
"""
from __future__ import annotations

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.agent.middleware import EnterpriseContext
from app.core.vectorstore import get_vectorstore

# 检索召回数
TOP_K = 5
# 距离阈值（重要）：langchain_chroma 的 similarity_search_with_score 返回的是
# “距离”，越小越相似（默认 l2 空间）。这里保留距离 <= 阈值的片段，过滤掉
# 不相关结果。该值与 embedding/距离度量强相关，需按实际数据调优。
MAX_DISTANCE = 1.5


def search_tenant_knowledge_base(query: str, tenant_id: str) -> str:
    """只在指定租户的向量分区中检索。"""
    vectorstore = get_vectorstore()
    results = vectorstore.similarity_search_with_score(
        query,
        k=TOP_K,
        filter={"tenant_id": tenant_id},
    )

    kept = [(doc, score) for doc, score in results if score <= MAX_DISTANCE]
    if not kept:
        return "未找到相关文档"

    blocks: list[str] = []
    for doc, _score in kept:
        source = doc.metadata.get("source", "未知文档")
        page = doc.metadata.get("page")
        if page is not None:
            tag = f"[来源:{source} 第{int(page) + 1}页]"
        else:
            tag = f"[来源:{source}]"
        blocks.append(f"{tag}\n{doc.page_content.strip()}")
    return "\n\n".join(blocks)


@tool
def search_knowledge_base(
    query: str,
    runtime: ToolRuntime[EnterpriseContext],
) -> str:
    """检索企业内部知识库，返回与问题最相关的文档片段。

    当用户的问题可能涉及公司内部的制度、流程、产品、文档或任何
    需要依据资料才能准确回答的内容时，调用本工具获取依据。

    Args:
        query: 用自然语言表述的检索问题。

    Returns:
        拼接后的相关片段（每段以 [来源:文件名 第X页] 开头）；
        若无命中则返回“未找到相关文档”。
    """
    return search_tenant_knowledge_base(query, runtime.context.tenant_id)

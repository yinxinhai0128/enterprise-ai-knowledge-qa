"""检索工具：把 Chroma 检索包装成 Agent 可调用的 @tool。

Agentic RAG 的关键：检索是一个工具，由 Agent 自主决定何时调用，
而不是固定先检索再回答。工具的 docstring 就是给模型看的调用说明。
"""
from __future__ import annotations

import math

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app.agent.context import EnterpriseContext
from app.core.evidence import Evidence
from app.core.faiss_store import faiss_similarity_search_with_score

# 检索召回数
TOP_K = 5
# 距离阈值：FAISS IndexFlatL2 返回 L2 距离（越小越相似），与 ChromaDB 默认度量相同。
# 对归一化嵌入向量，L2 距离范围 0–2；1.5 过滤掉不相关结果。
MAX_DISTANCE = 1.5


def search_tenant_knowledge_base(
    query: str,
    tenant_id: str,
) -> tuple[str, list[Evidence]]:
    """只在指定租户向量分区检索，返回模型内容与服务端 artifact。"""
    results = faiss_similarity_search_with_score(
        query,
        k=TOP_K,
        tenant_id=tenant_id,
    )

    kept = [(doc, score) for doc, score in results if score <= MAX_DISTANCE]
    if not kept:
        return "未找到相关文档", []

    blocks: list[str] = []
    artifact: list[Evidence] = []
    for doc, score in kept:
        metadata = doc.metadata
        chunk_id = str(metadata.get("chunk_id", ""))
        if not chunk_id:
            # 没有稳定 chunk ID 的异常结果不能成为可信证据。
            continue
        try:
            doc_id = int(metadata["doc_id"])
            distance = float(score)
            page = None if metadata.get("page") is None else int(metadata["page"])
        except (KeyError, TypeError, ValueError):
            continue
        if doc_id <= 0 or not math.isfinite(distance):
            continue
        item: Evidence = {
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "source": str(metadata.get("source", "未知文档")),
            "page": page,
            "sheet_name": (
                None
                if metadata.get("sheet_name") is None
                else str(metadata["sheet_name"])
            ),
            "distance": distance,
            "relevance": 1.0 / (1.0 + max(distance, 0.0)),
            "snippet": doc.page_content.strip()[:200],
        }
        artifact.append(item)
        blocks.append(
            "<UNTRUSTED_DOCUMENT_CONTENT "
            f'chunk_id="{chunk_id}">\n'
            f"{doc.page_content.strip()}\n"
            "</UNTRUSTED_DOCUMENT_CONTENT>"
        )
    if not artifact:
        return "未找到相关文档", []
    return "\n\n".join(blocks), artifact


@tool(response_format="content_and_artifact")
def search_knowledge_base(
    query: str,
    runtime: ToolRuntime[EnterpriseContext],
) -> tuple[str, list[Evidence]]:
    """检索企业内部知识库，返回与问题最相关的文档片段。

    当用户的问题可能涉及公司内部的制度、流程、产品、文档或任何
    需要依据资料才能准确回答的内容时，调用本工具获取依据。

    Args:
        query: 用自然语言表述的检索问题。

    Returns:
        content 是带不可信数据边界的相关片段；artifact 是服务端结构化证据；
        若无命中则 content 返回固定拒答提示且 artifact 为空。
    """
    return search_tenant_knowledge_base(query, runtime.context.tenant_id)

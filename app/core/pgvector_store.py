"""PostgreSQL + pgvector 向量存储，替代 FAISS 磁盘文件。

接口设计与 faiss_store.py 保持对齐，但全部为 async：
  - pgvector_similarity_search_with_score(query, k, tenant_id) -> list[tuple[Document, float]]
  - add_documents_to_pgvector(documents: list[Document]) -> None
  - delete_documents_from_pgvector(tenant_id, doc_id) -> int
  - pgvector_document_vector_ids(tenant_id, doc_id) -> list[str]
"""
from __future__ import annotations

import asyncio

from langchain_core.documents import Document as LCDocument
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.document import Document as DocumentRow
from app.models.document_chunk import DocumentChunk


async def pgvector_similarity_search_with_score(
    query: str,
    k: int = 5,
    tenant_id: str = "default",
) -> list[tuple[LCDocument, float]]:
    """余弦距离检索，返回 (Document, distance) 列表（distance 越小越相似，范围 0–2）。"""
    from app.core.llm import init_embeddings

    embeddings = init_embeddings()
    query_vec = await asyncio.to_thread(embeddings.embed_query, query)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(
                DocumentChunk,
                DocumentChunk.embedding.cosine_distance(query_vec).label("distance"),
            )
            .where(DocumentChunk.tenant_id == tenant_id)
            .order_by("distance")
            .limit(k)
        )
        rows = (await session.execute(stmt)).all()
        # 批量取 doc_id -> filename，填充 evidence 的 source 字段
        doc_ids = {chunk.doc_id for chunk, _ in rows}
        filename_map: dict[int, str] = {}
        if doc_ids:
            name_rows = (
                await session.execute(
                    select(DocumentRow.id, DocumentRow.filename).where(
                        DocumentRow.id.in_(doc_ids)
                    )
                )
            ).all()
            filename_map = {int(row[0]): str(row[1]) for row in name_rows}

    results: list[tuple[LCDocument, float]] = []
    for chunk, distance in rows:
        doc = LCDocument(
            page_content=chunk.content,
            metadata={
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "tenant_id": chunk.tenant_id,
                "page": chunk.page_number,
                "source": filename_map.get(chunk.doc_id, ""),
            },
        )
        results.append((doc, float(distance)))
    return results


async def add_documents_to_pgvector(documents: list[LCDocument]) -> None:
    """批量写入切片及向量（幂等：同 chunk_id 先删后插）。"""
    if not documents:
        return
    from app.core.llm import init_embeddings

    embeddings = init_embeddings()
    texts = [doc.page_content for doc in documents]
    vectors = await asyncio.to_thread(embeddings.embed_documents, texts)

    async with AsyncSessionLocal() as session:
        async with session.begin():
            chunk_ids = [str(doc.metadata.get("chunk_id", "")) for doc in documents]
            # 幂等删除已有相同 chunk_id 的记录
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.chunk_id.in_(chunk_ids))
            )
            chunks = [
                DocumentChunk(
                    chunk_id=str(doc.metadata.get("chunk_id", "")),
                    doc_id=int(doc.metadata["doc_id"]),
                    tenant_id=str(doc.metadata["tenant_id"]),
                    page_number=(
                        int(doc.metadata["page"]) if doc.metadata.get("page") is not None else None
                    ),
                    content=doc.page_content,
                    embedding=vec,
                )
                for doc, vec in zip(documents, vectors)
            ]
            session.add_all(chunks)


async def delete_documents_from_pgvector(tenant_id: str, doc_id: int) -> int:
    """删除指定文档的所有切片，返回删除数量。"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            result = await session.execute(
                delete(DocumentChunk)
                .where(
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.doc_id == doc_id,
                )
                .returning(DocumentChunk.id)
            )
            return len(result.all())


async def pgvector_document_vector_ids(tenant_id: str, doc_id: int) -> list[str]:
    """返回指定文档的所有 chunk_id 列表（用于一致性检查）。"""
    async with AsyncSessionLocal() as session:
        rows = await session.execute(
            select(DocumentChunk.chunk_id).where(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.doc_id == doc_id,
            )
        )
        return [r[0] for r in rows.all()]

"""向量切片存储模型：替代 FAISS 磁盘文件。"""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

EMBED_DIM = 1024  # text-embedding-v3 / bge-m3 输出维度


class DocumentChunk(Base):
    """文档切片及其向量表示。doc_id 级联删除保证孤向量不存在。"""

    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    doc_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<DocumentChunk chunk_id={self.chunk_id!r} doc_id={self.doc_id}>"

"""文档元数据模型：记录每个上传文件的摄入状态。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# 文档状态机：uploading -> parsing -> indexed / failed
DOC_STATUS = ("uploading", "parsing", "indexed", "failed")


class Document(Base):
    """一条记录对应一个上传的源文件。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 用户原始文件名（展示用）
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # 落盘路径（storage/ 下，文件名已加 uuid 前缀）
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    # 摄入状态，见 DOC_STATUS
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploading")
    # 入库的切片数量（成功后回填）
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 失败原因（成功为 NULL）
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 创建时间（数据库侧默认值）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Document id={self.id} filename={self.filename!r} status={self.status}>"

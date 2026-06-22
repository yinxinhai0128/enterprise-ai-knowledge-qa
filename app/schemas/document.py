"""文档相关的 API 出参模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    """文档信息出参（从 ORM 对象序列化）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    uploaded_by: str
    filename: str
    status: str
    chunk_count: int
    error_msg: str | None = None
    created_at: datetime

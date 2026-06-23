"""问答记录模型：审计中间件落库每轮问答。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatRecord(Base):
    """一条记录对应一轮问答（最终回答时落库）。"""

    __tablename__ = "chat_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # 会话标识（= 多轮记忆的 thread_id）
    session_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # 当前轮是否存在真实检索 artifact
    has_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 是否由服务端因缺少真实检索证据而拒答
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 是否命中敏感词、需转人工
    need_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tool_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sources: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    audit_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    audit_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_rule_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatRecord id={self.id} session={self.session_id} need_human={self.need_human}>"

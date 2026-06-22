"""问答记录模型：审计中间件落库每轮问答。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatRecord(Base):
    """一条记录对应一轮问答（最终回答时落库）。"""

    __tablename__ = "chat_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 会话标识（= 多轮记忆的 thread_id）
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # 回答是否带检索来源（含 "[来源:"）
    has_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 是否命中敏感词、需转人工
    need_human: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ChatRecord id={self.id} session={self.session_id} need_human={self.need_human}>"

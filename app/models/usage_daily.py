"""每日模型预算账本。"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UsageDaily(Base):
    """按 UTC 日期、租户和用户记录保守预留的模型费用边界。"""

    __tablename__ = "usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "usage_date",
            "tenant_id",
            "user_id",
            name="uq_usage_daily_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_calls_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

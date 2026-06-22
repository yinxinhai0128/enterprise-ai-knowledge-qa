"""问答接口的出入参模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """提问入参。"""

    question: str = Field(..., min_length=1, description="用户问题")
    user_id: str = Field(..., description="用户标识（审计用）")
    session_id: str = Field(..., description="会话标识，作为多轮记忆 thread_id")


class AskResponse(BaseModel):
    """回答出参。"""

    answer: str = Field(..., description="模型最终回答")
    sources: list[str] = Field(default_factory=list, description="回答中引用的来源标注")
    refused: bool = Field(..., description="是否因无相关资料而拒答")
    need_human: bool = Field(..., description="是否命中敏感词、需转人工")


class HistoryMessage(BaseModel):
    """单条历史消息。"""

    role: str = Field(..., description="user / assistant / tool / system")
    content: str = Field(..., description="消息文本")


class HistoryResponse(BaseModel):
    """会话历史出参。"""

    session_id: str
    messages: list[HistoryMessage]

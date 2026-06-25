"""问答接口的出入参模型。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.config import settings


class AskRequest(BaseModel):
    """提问入参。"""

    # 兼容旧客户端时忽略多余 user_id，但可信身份始终来自已验签 JWT。
    model_config = ConfigDict(extra="ignore")

    question: str = Field(
        ...,
        min_length=1,
        max_length=settings.max_question_chars,
        description="用户问题",
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=settings.max_session_id_chars,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
        description="客户端会话标识；服务端会与可信 tenant/user 组合成 thread ID",
    )


class EvidenceSource(BaseModel):
    """由检索工具 artifact 生成的结构化来源。"""

    doc_id: int
    chunk_id: str
    source: str
    page: int | None = None
    sheet_name: str | None = None
    distance: float
    relevance: float
    snippet: str = Field(default="", description="被引用的原文片段（前 200 字符），用于前端引用高亮")


class AskResponse(BaseModel):
    """回答出参。"""

    answer: str = Field(..., description="模型最终回答")
    sources: list[EvidenceSource] = Field(
        default_factory=list,
        description="来自真实检索 tool artifact 的结构化证据",
    )
    refused: bool = Field(..., description="是否因无相关资料而拒答")
    need_human: bool = Field(..., description="是否命中敏感词、需转人工")
    human_task_id: int | None = Field(
        default=None, description="已建立的人工任务 ID；无需人工时为空"
    )


class HistoryMessage(BaseModel):
    """单条历史消息。"""

    role: str = Field(..., description="user / assistant / tool / system")
    content: str = Field(..., description="消息文本")


class HistoryResponse(BaseModel):
    """会话历史出参。"""

    session_id: str
    messages: list[HistoryMessage]

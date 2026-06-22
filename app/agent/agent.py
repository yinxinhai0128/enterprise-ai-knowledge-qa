"""Agentic RAG 主体：create_agent 组装模型 + 检索工具 + 中间件。

遵循 LangChain 1.3 官方推荐：用 create_agent（retriever-as-tool），
不手写 StateGraph；多轮记忆用 InMemorySaver + thread_id。
"""
from __future__ import annotations

from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRetryMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
)
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.middleware import EnterpriseAuditMiddleware, EnterpriseContext
from app.core.llm import init_llm
from app.core.retriever_tool import search_knowledge_base

SYSTEM_PROMPT = """你是企业内部知识库助手。请严格遵守以下规则：

1. 只能基于 search_knowledge_base 工具检索到的文档内容回答问题，禁止依赖你自己的先验知识或编造信息。
2. 回答前，先判断是否需要检索；涉及公司制度、流程、产品或任何内部资料的问题，必须调用 search_knowledge_base。
3. 每一个论点都要标注来源，沿用检索片段中的 [来源:文件名 第X页] 标注格式。
4. 如果检索结果为“未找到相关文档”或与问题不相关，必须明确告知用户“知识库中没有找到相关资料”，不要强行作答。
5. 使用简体中文，回答简洁、准确、条理清晰。"""


@lru_cache(maxsize=1)
def build_agent():
    """构建并缓存 Agent 单例。"""
    model = init_llm()
    return create_agent(
        model=model,
        tools=[search_knowledge_base],
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            # 内置：输入侧脱敏 + 输出侧脱敏
            PIIMiddleware("email", strategy="redact", apply_to_output=True),
            PIIMiddleware("credit_card", strategy="mask", apply_to_output=True),
            # 内置：长对话自动摘要，避免上下文溢出
            SummarizationMiddleware(
                model=model,
                trigger={"tokens": 4000},
                keep=("messages", 20),
            ),
            # 内置：模型调用失败自动重试
            ModelRetryMiddleware(max_retries=2),
            # 自定义：敏感词拦截 + 问答审计落库
            EnterpriseAuditMiddleware(),
        ],
        context_schema=EnterpriseContext,
        checkpointer=InMemorySaver(),
    )

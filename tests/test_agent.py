"""Agent 与检索测试：有源标注 / 无源拒答 / 敏感转人工 / 多轮记忆。"""
from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from sqlalchemy import select

import app.core.database as database_module
from app.agent.middleware import EnterpriseContext
from app.core.retriever_tool import search_knowledge_base, search_tenant_knowledge_base
from app.core.vectorstore import migrate_legacy_vector_metadata
from app.models.chat_record import ChatRecord


def _ask_input(question: str):
    return {"messages": [{"role": "user", "content": question}]}


def _cfg(session_id: str):
    return {"configurable": {"thread_id": f"tenant-a:user-a:{session_id}"}}


def _ctx(session_id: str) -> EnterpriseContext:
    return EnterpriseContext(
        session_id=f"tenant-a:user-a:{session_id}",
        tenant_id="tenant-a",
        user_id="user-a",
    )


# ---------------- 检索工具（不经过 LLM，确定性） ----------------

def test_retriever_tool_returns_source(vectorstore):
    """库里有相关文档时，检索结果带 [来源:文件名] 前缀。"""
    vectorstore.add_texts(
        ["公司报销需先在系统提单并上传发票。"],
        metadatas=[{"source": "finance.txt", "tenant_id": "tenant-a"}],
    )
    result = search_tenant_knowledge_base("报销怎么走", "tenant-a")
    assert "[来源:" in result
    assert "finance.txt" in result


def test_retriever_tool_no_result(vectorstore):
    """空知识库检索返回固定话术“未找到相关文档”。"""
    result = search_tenant_knowledge_base("随便问问", "tenant-a")
    assert result == "未找到相关文档"


def test_retriever_tool_uses_runtime_tenant(vectorstore):
    """Agent 工具参数不暴露 tenant，实际过滤值来自可信 runtime context。"""
    vectorstore.add_texts(
        ["租户 A 专属资料。"],
        metadatas=[{"source": "a.txt", "tenant_id": "tenant-a"}],
    )
    assert "runtime" not in search_knowledge_base.args
    runtime = SimpleNamespace(context=_ctx("tool"))
    assert "a.txt" in search_knowledge_base.func("专属资料", runtime)


def test_legacy_vectors_are_migrated_fail_closed(vectorstore):
    """旧向量只归入 legacy；迁移前后均不会被普通租户检索到。"""
    vectorstore.add_texts(["旧资料"], metadatas=[{"source": "legacy.txt"}])
    assert search_tenant_knowledge_base("旧资料", "tenant-a") == "未找到相关文档"
    assert migrate_legacy_vector_metadata() == 1
    assert "legacy.txt" in search_tenant_knowledge_base("旧资料", "legacy")


# ---------------- Agent 行为 ----------------

async def test_agent_answer_with_source(agent_factory):
    """模型给出带来源的回答时，state.has_source 为真。"""
    agent = agent_factory(["根据资料，报销需提单。[来源:finance.txt 第1页]"])
    result = await agent.ainvoke(
        _ask_input("报销流程"), config=_cfg("s1"), context=_ctx("s1")
    )
    answer = result["messages"][-1].content
    assert "[来源:" in answer
    assert result.get("has_source") is True


async def test_agent_refuses_without_source(agent_factory):
    """无相关资料时模型明确拒答，has_source 为假。"""
    agent = agent_factory(["知识库中没有找到相关资料，无法回答。"])
    result = await agent.ainvoke(
        _ask_input("公司年会在哪开"), config=_cfg("s2"), context=_ctx("s2")
    )
    answer = result["messages"][-1].content
    assert "没有找到相关" in answer
    assert result.get("has_source") is False


async def test_agent_sensitive_word_needs_human(agent_factory):
    """问题命中敏感词（薪资）时标记 need_human，并落库记录。"""
    agent = agent_factory(["这个问题涉及薪资，建议联系 HR。"])
    result = await agent.ainvoke(
        _ask_input("帮我查一下我的薪资明细"),
        config=_cfg("s3"),
        context=_ctx("s3"),
    )
    assert result.get("need_human") is True

    # 审计中间件应把这轮问答写进 chat_records，且 need_human=True
    async with database_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(ChatRecord).where(
                    ChatRecord.session_id == "tenant-a:user-a:s3"
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].need_human is True
    assert rows[0].tenant_id == "tenant-a"
    assert rows[0].user_id == "user-a"


async def test_agent_multi_turn_memory(agent_factory):
    """同一 thread_id 多轮提问，checkpointer 累积历史（含两轮用户消息）。"""
    agent = agent_factory(["第一轮回答。", "第二轮回答。"])
    cfg = _cfg("s4")
    ctx = _ctx("s4")

    await agent.ainvoke(_ask_input("第一个问题"), config=cfg, context=ctx)
    await agent.ainvoke(_ask_input("第二个问题"), config=cfg, context=ctx)

    snapshot = await agent.aget_state(cfg)
    messages = snapshot.values.get("messages", [])
    human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
    assert len(human_msgs) == 2
    assert human_msgs[0].content == "第一个问题"
    assert human_msgs[1].content == "第二个问题"

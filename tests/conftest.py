"""测试夹具：全程 mock，不消耗任何真实 API、不写正式数据库。

设计要点：
  - 在导入 app 之前把 DATABASE_URL / STORAGE_DIR / CHROMA_DIR 指向临时目录，
    并补一个假的 DASHSCOPE_API_KEY，避免 Settings 因必填项报错。
  - 数据库引擎换成 NullPool：aiosqlite 在 pytest-asyncio 的每用例事件循环下，
    连接池复用会触发“Future attached to a different loop”，NullPool 每次新连接最稳。
  - LLM 用 GenericFakeChatModel 脚本化；Embedding 用 DeterministicFakeEmbedding；
    Chroma 用内存集合（无 persist_directory）。
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------- 必须在导入任何 app 模块之前设置环境 ----------
_TMP = tempfile.mkdtemp(prefix="kb_test_")
# sqlite URL 需用 posix 斜杠，避免 Windows 反斜杠被误解析
_DB_PATH = (Path(_TMP) / "test.db").as_posix()
os.environ.setdefault("DASHSCOPE_API_KEY", "test-key-not-used")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["STORAGE_DIR"] = _TMP
os.environ["CHROMA_DIR"] = _TMP
# 测试不得把假 Agent 调用上传到真实 LangSmith 项目。
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGSMITH_API_KEY"] = ""
os.environ["AUTH_JWT_SECRET"] = "test-only-jwt-secret-at-least-32-characters-long"
os.environ["AUTH_JWT_ISSUER"] = "test-idp"
os.environ["AUTH_JWT_AUDIENCE"] = "test-enterprise-kb"

import jwt  # noqa: E402
import pytest  # noqa: E402
from langchain_core.embeddings import DeterministicFakeEmbedding  # noqa: E402
from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

# ---------- 用 NullPool 引擎替换全局引擎（须在依赖模块导入前完成） ----------
import app.core.database as database_module  # noqa: E402

_test_engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
database_module.engine = _test_engine
database_module.AsyncSessionLocal = async_sessionmaker(
    _test_engine, expire_on_commit=False
)

from app.core.database import Base  # noqa: E402


@pytest.fixture
def auth_headers():
    """生成仅用于测试的已签名身份头，不调用真实身份系统。"""

    def _make(
        *,
        tenant_id: str = "tenant-a",
        user_id: str = "user-a",
        roles: tuple[str, ...] = ("user",),
    ) -> dict[str, str]:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {
                "sub": user_id,
                "tenant_id": tenant_id,
                "roles": list(roles),
                "iss": os.environ["AUTH_JWT_ISSUER"],
                "aud": os.environ["AUTH_JWT_AUDIENCE"],
                "iat": now,
                "exp": now + timedelta(minutes=5),
            },
            os.environ["AUTH_JWT_SECRET"],
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return _make


class FakeChatModel(GenericFakeChatModel):
    """脚本化假模型：按给定文本依次返回 AIMessage。

    create_agent 在绑定工具时会调用 bind_tools，这里直接返回自身（忽略工具），
    因为测试场景里我们直接脚本化最终回答，不需要真实的工具调用回环。
    """

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
        return self


@pytest.fixture
def fake_embeddings() -> DeterministicFakeEmbedding:
    """固定 1536 维的确定性假向量（同一文本 -> 同一向量）。"""
    return DeterministicFakeEmbedding(size=1536)


@pytest.fixture(autouse=True)
def mock_embeddings(monkeypatch, fake_embeddings):
    """自动替换所有 init_embeddings，杜绝任何真实 embedding 调用。"""
    monkeypatch.setattr("app.core.llm.init_embeddings", lambda **kw: fake_embeddings)
    monkeypatch.setattr(
        "app.core.vectorstore.init_embeddings", lambda **kw: fake_embeddings
    )
    return fake_embeddings


@pytest.fixture
def mock_llm(monkeypatch):
    """patch init_llm，返回固定 AIMessage 的假模型。"""
    model = FakeChatModel(messages=iter([AIMessage(content="这是一个测试回答。")]))
    monkeypatch.setattr("app.core.llm.init_llm", lambda **kw: model)
    monkeypatch.setattr("app.agent.agent.init_llm", lambda **kw: model)
    return model


@pytest.fixture
def vectorstore(monkeypatch, fake_embeddings):
    """内存 Chroma，并把各处 get_vectorstore 指向它；用例后清理集合。"""
    from langchain_chroma import Chroma

    store = Chroma(collection_name="test_kb", embedding_function=fake_embeddings)

    for module in ("app.core.vectorstore", "app.core.retriever_tool", "app.services.ingest"):
        monkeypatch.setattr(f"{module}.get_vectorstore", lambda: store)

    # 假向量的 l2 距离普遍较大，测试里放开距离阈值，保证有命中能被返回
    monkeypatch.setattr("app.core.retriever_tool.MAX_DISTANCE", float("inf"))

    yield store

    try:
        store.delete_collection()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def agent_factory(monkeypatch):
    """构造一个用脚本化假模型驱动的 Agent（复用真实中间件栈）。

    传入若干回答文本，模型按顺序返回；每次构造都清空 build_agent 缓存以拿到
    全新的 InMemorySaver（隔离多轮记忆）。
    """
    from app.agent.agent import build_agent

    def _make(responses: list[str | AIMessage]):
        messages = [
            response if isinstance(response, AIMessage) else AIMessage(content=response)
            for response in responses
        ]
        model = FakeChatModel(messages=iter(messages))
        monkeypatch.setattr("app.agent.agent.init_llm", lambda **kw: model)
        build_agent.cache_clear()
        return build_agent()

    yield _make
    build_agent.cache_clear()


@pytest.fixture(autouse=True)
async def _setup_db():
    """每个用例前建表、后清表，保证用例间互不污染。"""
    async with database_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with database_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client(auth_headers):
    """httpx 异步客户端（ASGI 直连，BackgroundTasks 会在响应前跑完）。"""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=auth_headers(),
    ) as ac:
        yield ac


@pytest.fixture
async def anonymous_client():
    """不带认证头的客户端，用于 401 验收。"""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

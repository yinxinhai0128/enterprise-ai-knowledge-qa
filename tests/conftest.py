"""测试夹具：全程 mock，不消耗任何真实 API、不写正式数据库。

设计要点：
  - 在导入 app 之前把 DATABASE_URL / STORAGE_DIR 指向临时目录，
    并补一个假的 DASHSCOPE_API_KEY，避免 Settings 因必填项报错。
  - 数据库引擎换成 NullPool：aiosqlite 在 pytest-asyncio 的每用例事件循环下，
    连接池复用会触发"Future attached to a different loop"，NullPool 每次新连接最稳。
  - LLM 用 GenericFakeChatModel 脚本化；Embedding 用 DeterministicFakeEmbedding；
    FAISS 用内存 store（monkeypatched，不落盘）。
"""
from __future__ import annotations

import gc
import os
import shutil
import socket
import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------- 必须在导入任何 app 模块之前设置环境 ----------
_TMP = tempfile.mkdtemp(prefix="kb_test_")
# sqlite URL 需用 posix 斜杠，避免 Windows 反斜杠被误解析
_DB_PATH = (Path(_TMP) / "test.db").as_posix()
os.environ.setdefault("DASHSCOPE_API_KEY", "test-key-not-used")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["STORAGE_DIR"] = _TMP
os.environ["CHECKPOINT_DB_PATH"] = str(Path(_TMP) / "checkpoints.db")
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

import app.models  # noqa: E402, F401  # 注册所有 ORM 表
from app.core.database import Base  # noqa: E402


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch):
    """测试进程禁止建立真实 socket 连接；ASGITransport 不受影响。"""

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def _is_loopback(address) -> bool:  # noqa: ANN001
        if not isinstance(address, tuple) or not address:
            return True
        return address[0] in {"127.0.0.1", "::1", "localhost"}

    def _guarded_connect(sock, address):  # noqa: ANN001
        if _is_loopback(address):
            return original_connect(sock, address)
        raise AssertionError("automated tests must not open network connections")

    def _guarded_create_connection(address, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if _is_loopback(address):
            return original_create_connection(address, *args, **kwargs)
        raise AssertionError("automated tests must not open network connections")

    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)


@pytest.fixture(autouse=True)
def _force_external_tracing_off():
    """任何自动化测试都先在 SDK 全局上下文强制关闭外部追踪。"""
    import langsmith as ls

    ls.configure(client=None, enabled=False, project_name=None, tags=None, metadata=None)
    yield
    ls.configure(client=None, enabled=False, project_name=None, tags=None, metadata=None)


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Generator[Path, None, None]:
    """Windows-safe tmp_path: bypasses pytest's numbered-directory accumulation
    which causes PermissionError when old directories are locked by the OS."""
    d = Path(tempfile.mkdtemp(prefix=f"pytest_{request.node.name[:20]}_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
async def _cleanup_test_runtime():
    """释放全局资源并删除本次 pytest 创建的唯一临时根目录。"""
    yield

    import app.core.faiss_store as _faiss_mod
    from app.agent.agent import build_agent
    from app.core.checkpointer import close_checkpointer
    from app.core.process_pool import shutdown_parser_pool

    build_agent.cache_clear()
    _faiss_mod._store = None  # 重置 FAISS 单例
    await close_checkpointer()
    await database_module.engine.dispose()
    shutdown_parser_pool()
    gc.collect()
    shutil.rmtree(_TMP, ignore_errors=False)


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
    """内存 FAISS，并把各处 FAISS 函数指向它；用例后无需清理（全在内存）。"""
    from langchain_community.vectorstores import FAISS as LangchainFAISS
    from langchain_core.documents import Document as LCDocument

    import app.core.faiss_store as _faiss_mod

    # 创建一个只含哨兵文档的内存 FAISS，然后删掉哨兵，得到空 store
    sentinel = LCDocument(
        page_content="_init_",
        metadata={"tenant_id": "__sentinel__", "doc_id": -1},
    )
    store = LangchainFAISS.from_documents([sentinel], fake_embeddings)
    sentinel_ids = list(store.docstore._dict.keys())
    store.delete(sentinel_ids)

    # 把模块级单例指向内存 store，get_faiss_store() 直接返回它
    monkeypatch.setattr(_faiss_mod, "_store", store)
    # 防止任何磁盘 I/O
    monkeypatch.setattr(_faiss_mod, "FAISS_INDEX_DIR", Path("/nonexistent_test"))

    # 补丁 add：写入内存 store，不落盘；用 chunk_id 作显式 ID 保证幂等性
    def _fake_add(documents):
        texts = [doc.page_content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        ids = [str(doc.metadata.get("chunk_id")) for doc in documents]
        existing = [id_ for id_ in ids if id_ in store.docstore._dict]
        if existing:
            store.delete(existing)
        store.add_texts(texts, metadatas=metadatas, ids=ids)

    monkeypatch.setattr(_faiss_mod, "add_documents_to_faiss", _fake_add)
    monkeypatch.setattr("app.services.ingest.add_documents_to_faiss", _fake_add)

    # 补丁 delete：从内存 store 删除，不落盘
    def _fake_delete(t_id: str, d_id: int) -> int:
        ids = [
            vid
            for vid, doc in store.docstore._dict.items()
            if str(doc.metadata.get("tenant_id")) == str(t_id)
            and int(doc.metadata.get("doc_id", -1)) == int(d_id)
        ]
        if ids:
            store.delete(ids)
        return len(ids)

    monkeypatch.setattr(_faiss_mod, "delete_documents_from_faiss", _fake_delete)
    monkeypatch.setattr("app.services.vector_ops.delete_documents_from_faiss", _fake_delete)

    # 假向量的 l2 距离普遍较大，测试里放开距离阈值，保证有命中能被返回
    monkeypatch.setattr("app.core.retriever_tool.MAX_DISTANCE", float("inf"))

    yield store
    # monkeypatch 会在用例结束后自动恢复所有 setattr，无需手动清理


@pytest.fixture
def agent_factory(monkeypatch):
    """构造一个用脚本化假模型驱动的 Agent（复用真实中间件栈）。

    传入若干回答文本，模型按顺序返回；每次构造都清空 build_agent 缓存以拿到
    全新的 InMemorySaver（隔离多轮记忆）。
    """
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agent.agent import build_agent

    def _make(responses: list[str | AIMessage]):
        messages = [
            response if isinstance(response, AIMessage) else AIMessage(content=response)
            for response in responses
        ]
        model = FakeChatModel(messages=iter(messages))
        monkeypatch.setattr("app.agent.agent.init_llm", lambda **kw: model)
        memory = InMemorySaver()
        monkeypatch.setattr("app.agent.agent.get_checkpointer", lambda: memory)
        build_agent.cache_clear()
        return build_agent()

    yield _make
    build_agent.cache_clear()


@pytest.fixture(autouse=True)
async def _setup_db():
    """每个用例前建表、后清表，保证用例间互不污染。"""
    from app.core.limits import request_limiter
    from app.core.observability import runtime_metrics

    await request_limiter.reset()
    runtime_metrics.reset()
    for directory in ("quarantine", "documents"):
        shutil.rmtree(Path(_TMP) / directory, ignore_errors=True)
    async with database_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    runtime_metrics.reset()
    async with database_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    for directory in ("quarantine", "documents"):
        shutil.rmtree(Path(_TMP) / directory, ignore_errors=True)


@pytest.fixture
async def client(auth_headers):
    """httpx 异步客户端（ASGI 直连；摄入任务由测试 Worker 显式执行）。"""
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
def worker_once():
    """执行一个持久化摄入任务，模拟独立 Worker 进程。"""
    from app.services.ingest_jobs import run_worker_once

    async def _run(**kwargs):
        return await run_worker_once(worker_id="test-worker", **kwargs)

    return _run


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

"""连通性自检脚本：跑通后再开发业务。

    python test_connection.py

依次验证：
  1) LLM 能调用百炼并返回内容（invoke「你好」）
  2) Embedding 能向量化并返回维度
  3) Chroma 能写入并检索（端到端最小闭环）
"""
from __future__ import annotations

import sys
from app.config import settings
from app.core.llm import init_embeddings, init_llm


def test_llm() -> bool:
    """测试对话大模型 invoke。"""
    print("\n[1/3] 测试 LLM 调用 …")
    try:
        llm = init_llm()
        resp = llm.invoke("你好，请用一句话介绍你自己。")
        print(f"  [OK] LLM={settings.llm_model} 返回：{resp.content[:80]}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] LLM 调用失败：{exc}")
        return False


def test_embedding() -> bool:
    """测试向量模型维度。"""
    print("\n[2/3] 测试 Embedding 向量化 …")
    try:
        embeddings = init_embeddings()
        vector = embeddings.embed_query("企业知识库连通性测试")
        print(f"  [OK] Embed={settings.embed_model} 维度={len(vector)}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] Embedding 调用失败：{exc}")
        return False


def test_chroma() -> bool:
    """测试 Chroma 写入与检索。"""
    store = None
    print("\n[3/3] 测试 Chroma 读写 …")
    try:
        from langchain_chroma import Chroma

        # 连通性检查无需验证持久化。使用内存集合可避免 Windows 下
        # Chroma/Rust 后端尚未释放 data_level0.bin 时清理临时目录失败。
        store = Chroma(
            collection_name="conn_test",
            embedding_function=init_embeddings(),
        )
        store.add_texts(
            texts=["本系统使用 LangChain 1.3 与 LangGraph 构建。"],
            metadatas=[{"source": "self-check"}],
        )
        hits = store.similarity_search("这个系统用什么框架？", k=1)
        print(f"  [OK] Chroma 检索命中：{hits[0].page_content}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] Chroma 读写失败：{exc}")
        return False
    finally:
        if store is not None:
            store.delete_collection()


def main() -> int:
    print("=" * 56)
    print(" 企业级 Agentic RAG 知识库 —— 连通性自检")
    print(f" 百炼地址：{settings.dashscope_base_url}")
    print("=" * 56)

    results = [test_llm(), test_embedding(), test_chroma()]

    print("\n" + "=" * 56)
    passed = sum(results)
    print(f" 结果：{passed}/{len(results)} 通过")
    print("=" * 56)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

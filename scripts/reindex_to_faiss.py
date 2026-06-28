"""重建 FAISS 向量索引：从原始文件重新切片、嵌入并保存。

chromadb 1.5.x Rust compactor 在本 Windows 机器上始终无法完成 HNSW 二进制构建，
因此切换到 faiss-cpu（有预构建 wheel，无需 MSVC）。

用法：
    python scripts/reindex_to_faiss.py
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import filter_complex_metadata
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.core.faiss_store import FAISS_INDEX_DIR
from app.core.llm import init_embeddings

SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=100,
    separators=["\n\n", "\n", "。", "!", "?", ",", " ", ""],
)


def _select_loader(path: Path):
    ext = path.suffix.lower()
    if ext == ".pdf":
        return PyPDFLoader(str(path))
    if ext == ".docx":
        return Docx2txtLoader(str(path))
    if ext in {".txt", ".md"}:
        for enc in ("utf-8-sig", "gbk"):
            try:
                path.read_text(encoding=enc)
                return TextLoader(str(path), encoding=enc)
            except UnicodeDecodeError:
                continue
        return TextLoader(str(path), encoding="utf-8-sig")
    raise ValueError(f"不支持的文件类型：{ext}")


def _load_and_split(path: Path, doc_id: int, source: str, tenant_id: str) -> list[Document]:
    loader = _select_loader(path)
    raw_docs = loader.load()
    chunks = SPLITTER.split_documents(raw_docs)
    for index, chunk in enumerate(chunks):
        content_hash = hashlib.sha256(chunk.page_content.encode("utf-8")).hexdigest()
        chunk_id = f"{tenant_id}:{doc_id}:{index}:{content_hash}"
        chunk.metadata.update({
            "doc_id": doc_id,
            "chunk_id": chunk_id,
            "content_hash": content_hash,
            "source": source,
            "chunk_index": index,
            "tenant_id": tenant_id,
            "uploaded_by": "system-reindex",
        })
    return filter_complex_metadata(chunks)


async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.connect() as conn:
        result = await conn.execute(text(
            "SELECT id, filename, file_path, tenant_id, status FROM documents ORDER BY id"
        ))
        docs = list(result.mappings())

    all_chunks: list[Document] = []
    for doc in docs:
        path = Path(doc["file_path"])
        if not path.exists():
            print(f"  SKIP id={doc['id']} — file not found: {path}")
            continue
        if doc["status"] != "indexed":
            print(f"  SKIP id={doc['id']} status={doc['status']}")
            continue
        print(f"  Loading id={doc['id']} {doc['filename']} ({path.stat().st_size:,} bytes)...")
        try:
            chunks = _load_and_split(path, doc["id"], doc["filename"], doc["tenant_id"])
            print(f"    -> {len(chunks)} chunks")
            all_chunks.extend(chunks)
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\nTotal chunks to embed: {len(all_chunks)}")
    if not all_chunks:
        print("Nothing to embed. Exiting.")
        return

    print("Embedding... (this calls the embedding API)")
    embeddings = init_embeddings()

    # Build FAISS index in batches to avoid rate limits
    BATCH = 100
    store: FAISS | None = None
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i : i + BATCH]
        texts = [c.page_content for c in batch]
        metadatas = [c.metadata for c in batch]
        print(f"  Batch {i//BATCH + 1}/{(len(all_chunks) + BATCH - 1)//BATCH}: {len(texts)} chunks...")
        vecs = embeddings.embed_documents(texts)
        if store is None:
            store = FAISS.from_embeddings(
                list(zip(texts, vecs)),
                embeddings,
                metadatas=metadatas,
            )
        else:
            store.add_embeddings(list(zip(texts, vecs)), metadatas=metadatas)

    if store is None:
        print("No store built.")
        return

    FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    store.save_local(str(FAISS_INDEX_DIR))
    print(f"\nFAISS index saved to {FAISS_INDEX_DIR}")
    print(f"Index contains {store.index.ntotal} vectors")

    # Quick smoke test
    print("\nSmoke test: searching for '龙族主角'...")
    results = store.similarity_search_with_score("龙族主角", k=3)
    for doc, score in results:
        print(f"  score={score:.4f} chunk_id={doc.metadata.get('chunk_id','?')[:40]}...")
        print(f"  snippet: {doc.page_content[:80]}")


if __name__ == "__main__":
    asyncio.run(main())

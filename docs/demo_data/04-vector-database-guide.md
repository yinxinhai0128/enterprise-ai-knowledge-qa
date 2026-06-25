# 向量数据库使用指南

## 概述

本项目使用 ChromaDB（`chromadb==1.5.9`）作为向量存储，通过 `langchain-chroma` 集成
LangChain 生态。Chroma 以嵌入式持久化模式运行，数据存储在 `chroma_db/` 目录下。

> ⚠️ **安全提示**：禁止启动 Chroma HTTP Server。当前版本存在 CVE-2026-45829，
> 尚无修复版。本项目只允许进程内嵌入式访问，补偿控制和升级计划见
> `docs/SUPPLY_CHAIN_AND_CHROMA_SECURITY.md`。

---

## 一、ChromaDB 基础概念

### Collection

Chroma 中的数据组织单位，类似关系数据库中的表。本项目使用单一 collection：

```python
COLLECTION_NAME = "enterprise_kb"
```

所有租户的文档共享这一 collection，通过 metadata 字段 `tenant_id` 实现逻辑隔离。

### 文档存储格式

每个向量条目包含：

```python
{
    "id": "tenant-a:42:0:ab12cd34",      # 稳定的 chunk ID
    "embedding": [0.023, -0.147, ...],    # 1024 维浮点向量
    "document": "文档的文本内容...",       # 原始文本
    "metadata": {
        "tenant_id": "tenant-a",
        "doc_id": 42,
        "source_filename": "技术规范.pdf",
        "chunk_index": 0,
        "content_hash": "ab12cd34",
        "created_at": "2026-06-23T10:00:00Z",
    }
}
```

---

## 二、嵌入向量

### 模型配置

本项目使用阿里云百炼 `text-embedding-v3`：

```python
from langchain_community.embeddings import DashScopeEmbeddings

embeddings = DashScopeEmbeddings(
    model="text-embedding-v3",
    dashscope_api_key=settings.dashscope_api_key,
)
```

### 向量维度

`text-embedding-v3` 输出 **1024 维**浮点数向量。维度越高，表达能力越强，但存储和
计算开销也更大。1024 维是文本语义检索的良好平衡点。

### 距离度量

Chroma 默认使用 **L2（欧几里得）距离**：

```
L2(a, b) = sqrt(sum((a_i - b_i)^2))
```

- 距离越小 → 语义越相似
- 距离为 0 → 完全相同的文本
- 典型距离范围：0.3（高相关）到 2.0+（低相关）

---

## 三、文档分块策略

### 分块器配置

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,     # 每块最多 500 字符
    chunk_overlap=50,   # 相邻块重叠 50 字符（保持上下文连续性）
    length_function=len,
    separators=["\n\n", "\n", "。", ".", " ", ""],
)
```

### 分块策略说明

| 参数 | 值 | 原因 |
|------|-----|------|
| `chunk_size` | 500 | 在检索精度和上下文完整性之间平衡；过小则缺乏上下文，过大则检索精度下降 |
| `chunk_overlap` | 50 | 防止关键信息被截断在两个 chunk 之间 |
| 分隔符优先级 | 段落 > 行 > 句号 > 空格 | 尽量在语义边界分割 |

### 不同格式的分块处理

| 文件类型 | Loader | 特殊处理 |
|----------|--------|---------|
| PDF | `PyPDFLoader` | 按页分割，保留页码元数据 |
| DOCX | `Docx2txtLoader` | 提取纯文本，保留段落结构 |
| TXT/MD | `TextLoader` | 直接处理，编码自动检测 |
| XLSX | `OpenPyXLAdapter` | 按 sheet 和行列展平为文本 |

---

## 四、稳定 Chunk ID

### ID 格式

```
{tenant_id}:{doc_id}:{chunk_index}:{content_hash[:8]}
```

示例：`tenant-a:42:0:ab12cd34`

### 设计原因

1. **幂等性**：相同内容的 chunk 生成相同 ID，重新索引不会产生重复条目
2. **可追溯**：ID 包含文档 ID，可以快速定位来源文档
3. **租户隔离**：不同租户的相同内容生成不同 ID（tenant_id 前缀）
4. **防碰撞**：content_hash 8 位十六进制（32 位碰撞概率极低）

### Content Hash 计算

```python
import hashlib

def compute_chunk_id(tenant_id: str, doc_id: int,
                     chunk_index: int, content: str) -> str:
    content_hash = hashlib.md5(content.encode()).hexdigest()
    return f"{tenant_id}:{doc_id}:{chunk_index}:{content_hash[:8]}"
```

---

## 五、相关度计算

### 距离转相关度

API 返回给前端的 `relevance_score` 由 L2 距离换算：

```python
def distance_to_relevance(distance: float) -> float:
    """
    将 L2 距离（越小越相关）转换为相关度分数（越大越相关）。
    公式：1 / (1 + distance)，输出范围 (0, 1]。
    """
    return 1.0 / (1.0 + max(distance, 0.0))
```

| L2 距离 | 相关度分数 | 主观感受 |
|---------|-----------|---------|
| 0.0 | 1.000 | 完全相同 |
| 0.3 | 0.769 | 高度相关 |
| 0.8 | 0.556 | 中度相关 |
| 1.5 | 0.400 | 边界相关（过滤阈值） |
| 2.0 | 0.333 | 低相关（已被过滤） |

### 距离阈值

```python
MAX_DISTANCE = 1.5   # 超过此距离的检索结果被丢弃
```

设为 1.5 的依据：
- 低于 1.5：通常与问题有实质性语义关联
- 高于 1.5：往往是随机相关或无关内容，纳入 Prompt 反而干扰 LLM

---

## 六、索引操作

### 文档入库流程

```python
# 1. 解析文件
loader = get_loader(file_path, file_ext)
raw_docs = loader.load()

# 2. 分块
chunks = splitter.split_documents(raw_docs)

# 3. 添加元数据
for i, chunk in enumerate(chunks):
    chunk_id = compute_chunk_id(tenant_id, doc_id, i, chunk.page_content)
    chunk.metadata.update({
        "tenant_id": tenant_id,
        "doc_id": doc_id,
        "chunk_index": i,
        "content_hash": hashlib.md5(chunk.page_content.encode()).hexdigest()[:8],
    })

# 4. 入库（langchain-chroma 自动处理向量化）
vectorstore.add_documents(chunks, ids=[compute_chunk_id(...) for ...])
```

### 删除文档向量

```python
def delete_document_vectors(tenant_id: str, doc_id: int) -> int:
    """删除指定文档的所有 chunk，返回删除数量。"""
    collection = get_collection()
    results = collection.get(
        where={"tenant_id": tenant_id, "doc_id": doc_id},
        include=[],  # 只要 ID
    )
    if results["ids"]:
        collection.delete(ids=results["ids"])
    return len(results["ids"])
```

### 重新索引

先删除旧向量，再重新解析文件并入库：

```python
# 1. 删除旧向量（保持 Chroma 与 SQLite 一致）
delete_document_vectors(tenant_id, doc_id)

# 2. 重新解析和入库
ingest_document(document)
```

---

## 七、一致性维护

### 三层数据源

本项目有三个需要保持一致的数据源：

| 层 | 内容 | 位置 |
|----|------|------|
| SQLite | 文档元数据、状态、摄入任务 | `storage/app.db` |
| 文件存储 | 原始上传文件 | `storage/` |
| ChromaDB | 向量化 chunk | `chroma_db/` |

### 一致性巡检（`app/services/consistency.py`）

定期执行以下检查：

1. **孤立向量检测**：Chroma 中存在但 SQLite 中文档已删除的 chunk
2. **文件缺失检测**：SQLite 记录文档但对应文件不存在
3. **状态不一致检测**：文档状态为 `indexed` 但 Chroma 中无对应 chunk

发现不一致时记录到审计日志，由运维人员介入处理。

---

## 八、性能调优建议

### 小规模（< 10 万文档）

默认配置，无需调整。Chroma 嵌入式模式对此规模性能充足。

### 中规模（10 万 - 100 万文档）

- 考虑增加 `chunk_size`（700-1000）以减少向量数量
- 调整 `n_results`（减少到 3）降低检索延迟
- 确保 `chroma_db/` 在 SSD 上

### 大规模（> 100 万文档）

- 评估迁移到 Milvus、Weaviate 或 Qdrant 等分布式向量数据库
- 需要重新评估租户隔离策略（collection per tenant 或 namespace）
- Chroma 嵌入式模式不适合此规模，需要架构升级

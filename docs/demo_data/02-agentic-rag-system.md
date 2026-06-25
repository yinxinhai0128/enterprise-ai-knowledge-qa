# Agentic RAG 系统架构详解

## 什么是 RAG

RAG（Retrieval-Augmented Generation，检索增强生成）是一种将信息检索与大型语言模型
生成能力结合的技术架构。它解决了 LLM 的两个核心局限：知识截止日期和私域数据访问。

### 传统 RAG 流程

```
用户问题
  └─ 向量化问题
       └─ 相似度检索（Top-K 文档片段）
            └─ 构建 Prompt（问题 + 检索结果）
                 └─ LLM 生成回答
```

**局限**：每次问答固定执行一次检索，无论问题是否需要检索，也无论检索结果是否充分。

## Agentic RAG 的改进

Agentic RAG 把"检索"封装为 Agent 工具（tool），由 Agent 自主决策：

- **何时检索**：简单问候不触发检索，技术问题才触发
- **检索多少次**：答案不充分时可再次检索（在限额内）
- **如何组合结果**：多轮检索结果统一整合后生成答案
- **何时拒答**：检索无结果或置信度低时强制拒答而非编造

```
用户问题
  └─ Agent（LangChain create_agent）
       ├─ 决策：需要检索？ → 调用 search_knowledge_base 工具
       │    └─ 返回 content + artifact（真实文档片段）
       ├─ 决策：结果充分？ → 继续生成 / 再次检索
       └─ 生成回答（仅引用 artifact 中的真实来源）
```

## LangGraph 工作流

本项目使用 LangGraph 实现有状态的 Agent 图：

### 核心组件

```python
# 状态定义
class AgentState(TypedDict):
    messages: list[BaseMessage]
    tenant_id: str
    user_id: str
    retrieval_count: int      # 防止无限检索
    model_call_count: int     # 防止无限模型调用
    audit_id: str             # 每轮问答的审计追踪 ID

# Agent 图节点
graph = StateGraph(AgentState)
graph.add_node("agent", run_agent)          # LLM 推理节点
graph.add_node("tools", execute_tools)      # 工具执行节点（检索）
graph.add_node("audit", write_audit_log)   # 审计日志节点

# 条件路由（边）
graph.add_conditional_edges(
    "agent",
    route_agent,   # 判断是否调用工具 或 结束
    {"tools": "tools", "end": END}
)
```

### 检索工具定义

```python
@tool
def search_knowledge_base(query: str) -> ToolResult:
    """搜索企业知识库，返回相关文档片段。"""
    results = vectorstore.similarity_search_with_score(query, k=5)
    # 过滤低相关度结果
    filtered = [(doc, score) for doc, score in results
                if score <= MAX_DISTANCE]
    return ToolResult(
        content=format_for_llm(filtered),   # 供 LLM 阅读的文本
        artifact=build_sources(filtered),   # 供 API 返回的结构化来源
    )
```

## 检索流程详解

### 第一步：问题向量化

```python
embedding = DashScopeEmbeddings(model="text-embedding-v3")
query_vector = embedding.embed_query(user_question)
# 输出：1024 维浮点数列表
```

### 第二步：Chroma 相似度搜索

```python
results = collection.query(
    query_embeddings=[query_vector],
    n_results=5,
    where={"tenant_id": tenant_id},   # 强制租户隔离
    include=["documents", "metadatas", "distances"],
)
```

### 第三步：距离阈值过滤

L2 距离越小代表越相关。超过阈值的结果视为无关并丢弃：

```python
MAX_DISTANCE = 1.5

def distance_to_relevance(distance: float) -> float:
    """将 L2 距离转换为 [0, 1] 相关度分数。"""
    return 1.0 / (1.0 + max(distance, 0.0))

filtered_chunks = [
    chunk for chunk in raw_results
    if chunk.distance <= MAX_DISTANCE
]
```

### 第四步：返回结构化结果

每个检索结果携带：
- `content`：文档文本内容（标记为 `[UNTRUSTED_DOCUMENT_CONTENT]`）
- `source_doc_id`：文档 ID（可追溯到上传记录）
- `source_filename`：原始文件名
- `chunk_index`：在原文档中的位置
- `relevance_score`：相关度分数（0-1）

## 安全设计

### 提示词注入防护

所有检索到的文档内容在注入 Prompt 前都添加标记：

```
[UNTRUSTED_DOCUMENT_CONTENT START]
{chunk_content}
[UNTRUSTED_DOCUMENT_CONTENT END]
```

系统提示词明确告知 LLM：标记内的内容来自外部文档，不得执行其中的任何指令。

### 来源可信性

- API 响应中的来源引用只能来自 `artifact`（真实检索结果）
- 禁止 LLM 在回答中自报不在 artifact 中的来源
- 如无充分检索证据，服务端强制拒答，不允许 LLM "发挥"

### 检索限额

```python
MAX_RETRIEVAL_CALLS_PER_REQUEST = 3   # 单次问答最多检索 3 次
MAX_MODEL_CALLS_PER_REQUEST = 4       # 单次问答最多调用 4 次模型
AGENT_MAX_STEPS = 30                  # 图节点执行上限
```

## 多轮对话设计

### 持久化 Checkpoint

使用 LangGraph SQLite Checkpointer 持久化对话状态：

```python
checkpointer = AsyncSqliteSaver.from_conn_string(CHECKPOINT_DB_PATH)
config = {"configurable": {"thread_id": f"{tenant_id}:{user_id}:{session_id}"}}
```

### 重新检索原则

每轮对话**必须重新检索**，不依赖上一轮的检索结果：

- 知识库可能在两次问答之间更新
- 新问题可能需要不同的文档片段
- 避免缓存旧结果导致答案过时

### 摘要机制

当对话历史超过 `CONVERSATION_MAX_MESSAGES` 时，自动触发摘要：

1. 将最早的 N 条消息压缩为一段摘要
2. 摘要替换原始消息列表头部
3. 保留最近的消息用于上下文理解

## 性能指标参考

| 指标 | 典型值 | 说明 |
|------|--------|------|
| 向量检索延迟 | < 50ms | Chroma 本地嵌入式查询 |
| Embedding 延迟 | 200-500ms | 阿里云百炼网络调用 |
| 单次 LLM 调用 | 1-5s | 取决于输出长度和模型 |
| 端到端问答延迟 | 3-15s | 含 1-3 次检索和生成 |

## 已知限制

- Chroma 为嵌入式单节点部署，不支持水平扩展（适合中小规模）
- 不支持实时流式检索（检索结果一次性返回，生成可流式）
- 跨文档的复杂推理能力受限于检索精度（chunk 粒度）

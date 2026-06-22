# syntax=docker/dockerfile:1
# ============================================================
# 企业级 Agentic RAG 知识库 —— 运行镜像
# 基础镜像：python:3.12-slim，以非 root 用户运行
# ============================================================
FROM python:3.12-slim

# 不写 .pyc、日志实时刷新
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 先装依赖以利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝项目源码
COPY . .

# 创建非 root 用户，并把可写目录交给它
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/storage /app/chroma_db /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 容器健康检查，命中 /health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

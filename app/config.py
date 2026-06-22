"""全局配置：用 pydantic-settings 读取 .env，单例提供。

其它模块统一通过 `from app.config import settings` 使用，
切勿在业务代码里直接读环境变量或硬编码密钥 / 地址。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（app/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent

# LangSmith 等第三方库直接读取 os.environ，而 BaseSettings 只会把 .env
# 解析到 Settings 对象中。启动早期加载一次，且不覆盖 Docker/系统环境变量。
load_dotenv(BASE_DIR / ".env", override=False)


class Settings(BaseSettings):
    """从 .env / 环境变量加载的强类型配置。"""

    # ---------- 百炼（DashScope OpenAI 兼容） ----------
    dashscope_api_key: str = Field(..., description="百炼 API Key")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        description="OpenAI 兼容接口基础地址",
    )

    # ---------- 模型 ----------
    llm_model: str = Field(default="deepseek-v3", description="对话大模型")
    embed_model: str = Field(default="text-embedding-v3", description="向量模型")
    llm_max_output_tokens: int = Field(default=2048, ge=1, le=8192)
    agent_max_steps: int = Field(default=30, ge=3, le=50)
    max_model_calls_per_request: int = Field(default=4, ge=1, le=20)
    max_retrieval_calls_per_request: int = Field(default=3, ge=1, le=20)

    # ---------- LangSmith 可观测 ----------
    langsmith_api_key: str = Field(default="", description="LangSmith API Key，可空")
    langchain_tracing_v2: bool = Field(default=False, description="是否开启链路追踪")
    langchain_project: str = Field(default="enterprise-kb", description="LangSmith 项目名")

    # ---------- 应用 ----------
    app_env: Literal["development", "production"] = Field(
        default="development", description="运行环境"
    )
    app_host: str = Field(default="127.0.0.1", description="服务监听地址")
    app_port: int = Field(default=8000, description="服务监听端口")
    log_level: str = Field(default="INFO", description="日志级别")

    # ---------- 请求、并发与每日费用边界 ----------
    max_question_chars: int = Field(default=4000, ge=1, le=100_000)
    max_session_id_chars: int = Field(default=64, ge=1, le=128)
    qa_rate_limit_per_minute: int = Field(default=30, ge=1)
    upload_rate_limit_per_minute: int = Field(default=10, ge=1)
    admin_rate_limit_per_minute: int = Field(default=60, ge=1)
    qa_max_concurrency: int = Field(default=8, ge=1)
    upload_max_concurrency: int = Field(default=2, ge=1)
    admin_max_concurrency: int = Field(default=10, ge=1)
    daily_user_model_calls: int = Field(default=200, ge=1)
    daily_tenant_model_calls: int = Field(default=5000, ge=1)
    daily_user_token_budget: int = Field(default=500_000, ge=1)
    daily_tenant_token_budget: int = Field(default=10_000_000, ge=1)

    # ---------- 上传、压缩包与解析器资源边界 ----------
    max_filename_chars: int = Field(default=200, ge=1, le=255)
    max_file_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1)
    upload_chunk_bytes: int = Field(default=1024 * 1024, ge=4096)
    upload_write_timeout_seconds: float = Field(default=30.0, gt=0)
    file_validation_timeout_seconds: float = Field(default=30.0, gt=0)
    parser_timeout_seconds: float = Field(default=120.0, gt=0)
    parser_workers: int = Field(default=2, ge=1, le=8)
    max_archive_entries: int = Field(default=2000, ge=1)
    max_archive_uncompressed_bytes: int = Field(
        default=100 * 1024 * 1024, ge=1
    )
    max_archive_compression_ratio: float = Field(default=100.0, gt=1.0)
    max_pdf_pages: int = Field(default=500, ge=1)
    max_xlsx_sheets: int = Field(default=100, ge=1)
    max_xlsx_cells: int = Field(default=1_000_000, ge=1)
    max_parsed_chars: int = Field(default=2_000_000, ge=1)
    malware_scan_required: bool = Field(default=False)

    # ---------- 身份认证（HS256 JWT，仅验证，不提供 Token 签发接口） ----------
    auth_jwt_secret: SecretStr = Field(
        default=SecretStr(""), description="JWT HMAC 密钥，至少 32 字符"
    )
    auth_jwt_issuer: str = Field(default="enterprise-idp", description="JWT issuer")
    auth_jwt_audience: str = Field(default="enterprise-kb", description="JWT audience")

    # ---------- 路径（容器内 /app 下，与挂载卷对齐） ----------
    storage_dir: Path = Field(default=BASE_DIR / "storage", description="业务文件存储目录")
    chroma_dir: Path = Field(default=BASE_DIR / "chroma_db", description="Chroma 持久化目录")
    log_dir: Path = Field(default=BASE_DIR / "logs", description="日志目录")

    # ---------- 数据库（SQLite + aiosqlite，落在 storage/ 下随卷持久化） ----------
    database_url: str = Field(
        default=f"sqlite+aiosqlite:///{(BASE_DIR / 'storage' / 'app.db').as_posix()}",
        description="异步数据库连接串",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def ensure_dirs(self) -> None:
        """确保运行所需的可写目录存在。"""
        for path in (
            self.storage_dir,
            self.storage_dir / "quarantine",
            self.storage_dir / "documents",
            self.chroma_dir,
            self.log_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例：进程内只解析一次 .env。"""
    return Settings()


# 模块级单例，供全项目导入使用
settings = get_settings()

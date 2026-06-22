"""全局配置：用 pydantic-settings 读取 .env，单例提供。

其它模块统一通过 `from app.config import settings` 使用，
切勿在业务代码里直接读环境变量或硬编码密钥 / 地址。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
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
        for path in (self.storage_dir, self.chroma_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """单例：进程内只解析一次 .env。"""
    return Settings()


# 模块级单例，供全项目导入使用
settings = get_settings()

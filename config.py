"""项目配置: 从 .env 读取敏感信息(数据库连接等),禁止硬编码进代码。"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[0]
ENV_PATH = PROJECT_ROOT / ".env"


def _load_env(path: Path = ENV_PATH) -> None:
    """极简 .env 加载(键=值,支持 # 注释),避免依赖 python-dotenv。"""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env()

DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/auction"
)

# ─── 智能体 LLM 基座(阿里云百炼 DashScope, OpenAI 兼容模式) ───
# .env 键名沿用用户定义: AliBaseURL / AliAPIKey / AliLLM
ALI_BASE_URL: str = os.getenv(
    "AliBaseURL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
ALI_API_KEY: str = os.getenv("AliAPIKey", "")
ALI_MODEL: str = os.getenv("AliLLM", "qwen-plus")
ALI_TIMEOUT: int = int(os.getenv("AliTimeout", "180"))
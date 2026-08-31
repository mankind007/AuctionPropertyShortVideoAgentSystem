"""Web 应用配置：从顶层 config 读取并提供 Settings 单例。"""
from __future__ import annotations

from functools import lru_cache

import config


class Settings:
    """Web 专用配置（只读代理顶层 config）。"""

    @property
    def JWT_SECRET(self) -> str:
        return config.JWT_SECRET

    @property
    def JWT_ALGO(self) -> str:
        return config.JWT_ALGO

    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        return config.ACCESS_TOKEN_EXPIRE_MINUTES

    @property
    def UPLOAD_DIR(self) -> str:
        return config.UPLOAD_DIR

    @property
    def UPLOAD_MAX_MB(self) -> int:
        return config.UPLOAD_MAX_MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
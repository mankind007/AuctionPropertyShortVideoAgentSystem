"""LLM 模型基座: 阿里云百炼 DashScope(OpenAI 兼容模式) 统一访问入口。

用法(供所有智能体任务复用):
    from agent.model import chat
    reply = chat(system="...", user="...", json_mode=True)

行为约定:
- 读顶层 config.py 的 ALI_BASE_URL / ALI_API_KEY / ALI_MODEL(.env: AliBaseURL/AliAPIKey/AliLLM)。
- 未配置 API key → 抛 LLMConfigError(调用方捕获后降级), 绝不静默吞掉。
- 对 限流/网络抖动/超时 做有限重试; 认证/模型不存在/内容错误 等 4xx 直接抛出(重试无意义)。
"""
from __future__ import annotations

from typing import Optional

import config


class LLMError(Exception):
    """LLM 调用异常基类。"""


class LLMConfigError(LLMError):
    """配置缺失(如 API key 为空)。"""


class LLMErrorLimit(LLMError):
    """不可重试的调用失败(认证失败/模型不存在/内容错误等)。"""


def chat(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.8,
    timeout: Optional[int] = None,
    max_retry: int = 2,
    json_mode: bool = True,
    max_tokens: int = 4000,
) -> str:
    """调用通义千问, 返回回复正文。JSON 模式失败会回退普通模式再试一次。"""
    if not config.ALI_API_KEY:
        raise LLMConfigError("AliAPIKey 未配置(.env), 无法调用 LLM")

    from openai import OpenAI
    from openai import APIConnectionError, APITimeoutError, RateLimitError

    client = OpenAI(api_key=config.ALI_API_KEY, base_url=config.ALI_BASE_URL,
                    timeout=timeout or config.ALI_TIMEOUT, max_retries=0)
    model = model or config.ALI_MODEL

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    last_exc: Optional[Exception] = None
    for attempt in range(max_retry + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            if content is None or not content.strip():
                raise LLMErrorLimit("LLM 返回空内容")
            return content.strip()
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            last_exc = exc
            if attempt < max_retry:
                import time
                time.sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"LLM 网络/限流重试后仍失败: {type(exc).__name__}: {exc}") from exc
        except Exception as exc:  # 认证/模型不存在/内容策略等 4xx 不重试
            raise LLMErrorLimit(f"LLM 调用失败(不可重试): {type(exc).__name__}: {exc}") from exc
    raise LLMError(f"LLM 调用失败: {last_exc}")

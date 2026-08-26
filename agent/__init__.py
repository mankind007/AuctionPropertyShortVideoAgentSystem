"""智能体核心层(LLM 基座 + 任务模块)。

- model.py: 模型访问基座(阿里云百炼 DashScope, OpenAI 兼容), 全项目复用。
- tasks/: 各智能体具体任务(话术生成在 skills/script-writer, 其余任务后续平级扩展)。
"""

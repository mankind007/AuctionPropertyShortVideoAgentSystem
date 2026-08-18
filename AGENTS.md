# AGENTS.md

本文件为 Agent 在本仓库工作时的必读指引。任何改动前先读本文件与 `docs/初步信息.txt`、`plans/法拍房短视频智能体系统初步计划.txt`。

## 项目概述

本地部署的法拍房短视频智能体系统:自动采集法拍房源(公拍网/阿里资产),清洗数据、去水印、生成话术、TTS 配音、合成短视频、风险校验、多平台自动发布。

技术栈: Python 3.10、playwright、langchain、langgraph、pandas、SQLAlchemy、PostgreSQL。

## 目录职责与约定

| 目录 | 职责 | 约定 |
|------|------|------|
| `skills/` | Agent 技能库 | 每个技能 = 目录 + `SKILL.md`(必需),可选 `scripts/` `references/` `assets/` |
| `scripts/` | 人工独立运行脚本 | CLI 入口,带 argparse/--help,可被人工直接运行 |
| `app/` | 应用主包(纯应用逻辑) | `schemas/`=DTO, `orchestrator.py`=多源编排 |
| `db/` | 数据库层 | `listing.py`=ORM, `db.py`=engine/session/upsert, `__init__.py` 统一出口 |
| `config.py` | 顶层配置 | 读 `.env` 的 `DATABASE_URL` 等,供 db/scripts/skills 复用 |
| `utils/` | 跨技能底层工具 | ffmpeg 封装、HTTP 重试、日志等 |
| `tests/` | 测试 | 每个 skill 对应 `tests/test_<skill>.py` |
| `assets/` | 文件流水线 | 按 `listing_id` 分桶,桶内按阶段分层(raw/cleaned/script/voice/video) |
| `reports/` | 进度记录 | 每完成里程碑在 `reports/PROGRESS.md` 追加记录 |
| `docs/` | 调研信息 | 数据源 XPath 规则等 |
| `plans/` | 计划 | 整体实施计划 |

## Skill 编写规范(Agent Skills 规范)

Skill 的最小单元是目录,核心是 `SKILL.md`:

```
skill-name/
├── SKILL.md          # 必需: YAML frontmatter + Markdown 指令
├── scripts/          # 可选: 可执行代码(自包含或注明依赖)
├── references/       # 可选: 按需加载的参考文档
└── assets/           # 可选: 模板/静态资源
```

- `SKILL.md` 顶部 YAML frontmatter 必填:
  - `name`: 小写字母/数字/连字符,与父目录名一致
  - `description`: 写清**做什么 + 何时触发 + 触发关键词**,决定 Agent 能否命中
- 正文(instructions)控制在 500 行内;长资料拆到 `references/`,用相对路径(一级深度)引用
- 代码放 `scripts/`,脚本必须能被人工直接运行(自包含、清晰错误提示、`--help`)
- 渐进式加载: 元数据启动时加载,正文激活时加载,资源按需加载

## 架构与数据流

```
爬虫(skills) → 原始数据/图片(assets) → 清洗 → 风险校验 → 入库(db) → 视频生成 → TTS → 合成 → 发布
```

- **双通道运行**: 人工跑 `scripts/`,Agent 通过 skill 的 `SKILL.md` 触发;两者复用同一套 skill `scripts/` 逻辑
- **模型分层**: `db/listing.py`(ORM 持久化)与 `app/schemas/`(跨技能 DTO)分离,解耦存储与接口
- **配置安全**: API key、数据库密码一律走 `.env` + 顶层 `config.py`,禁止硬编码进代码或 skill
- **断点续跑**: assets 以 `listing_id` + 阶段原子写,DB 存路径/状态作为事实源

## 环境

- 激活虚拟环境: Windows `.venv\Scripts\Activate.ps1`; macOS/Linux `source .venv/bin/activate`
- 依赖已装: playwright、langchain、langgraph、pandas、SQLAlchemy
- PostgreSQL 本机 localhost,连接信息见 `docs/初步信息.txt`

## 数据源要点(来自 docs/初步信息.txt)

- **公拍网**: 房产筛选 `https://s.gpai.net/sf/Search.do?at=376`,不登录可获取数据和图片
  - `restate=1` 即将开始, `restate=2` 正在拍卖
  - 列表页每页最多16条,`//div[@class='filtbar-l fl']/span/label` 显示总数
  - 详情页小图 `//ul[@class='small-pics clearfix']/li/a/@rev`,需加 `https:` 前缀
  - 完整 XPath 规则见 `docs/初步信息.txt`,实现时以此为基准
- **阿里资产**: 方式1 爬虫,方式2 API(待调研)

## 测试

- 运行: `pytest tests/`(在虚拟环境中)
- 每个 skill 一个测试文件,优先做契约测试(输入/输出结构不变即通过)

## 进度维护

- 完成任何功能后,更新 `reports/PROGRESS.md`(追加记录,注明日期与状态)

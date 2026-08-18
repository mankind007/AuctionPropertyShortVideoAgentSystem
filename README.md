# 法拍房短视频智能体系统 (Auction Property Short Video Agent System)

本地部署的法拍房短视频智能体系统:自动采集法拍房源(公拍网/阿里资产)数据与图片,清洗结构化数据,去除图片水印,生成话术并配 TTS 语音,合成短视频,经风险校验后自动发布到多平台。

## 项目目标

按 `plans/法拍房短视频智能体系统初步计划.txt` 落地一条完整的自动化流水线:

1. 数据采集(公拍网爬虫 + 阿里资产爬虫/API)
2. 数据清洗(结构化直接入表,非结构化用规则/AI 抽取)
3. 图片去水印
4. 图文合成初步视频(图片 + 数据 + 话术 + 字体)
5. TTS 配音
6. 风险校验
7. 音视频合成完整视频
8. 多平台自动发布

## 目录结构

```
.
├── app/               # 应用主包:schemas(DTO)、orchestrator(多源编排)
├── scripts/           # 人工可直接运行的独立脚本(CLI 入口)
├── skills/            # Agent 技能库:每个技能 = 目录 + SKILL.md(附 scripts/references/assets)
├── db/                # 数据库层:listing.py(ORM)、db.py(engine/session/upsert)
├── config.py          # 顶层配置:读 .env(如 DATABASE_URL)
├── utils/             # 跨技能底层工具(浏览器封装、图片下载重试、网络重试、解析等)
├── tests/             # 单元/集成测试,每个 skill 对应测试
├── assets/            # 文件流水线:按 listing_id 分桶 + 阶段分层(详见下)
│   ├── templates/     # 全局共享素材(fonts/ 字体、overlays/ 片头尾模板)
│   ├── {listing_id}/  # 每拍品: raw/原始图 → cleaned/去水印图 → script.json → voice.mp3 → video.mp4
│   └── published/     # 发布记录/截图
├── reports/           # 进度与里程碑记录(PROGRESS.md)
├── docs/              # 调研与信息收集(数据源 XPath 规则等)
└── plans/             # 整体计划
```

## 环境要求

- Python 3.10(见 `.python-version`)
- 已安装: playwright、langchain、langgraph、pandas、SQLAlchemy
- PostgreSQL(本机 localhost)

## 快速开始

### 激活虚拟环境

- Windows(PowerShell): `.venv\Scripts\Activate.ps1`
- macOS / Linux: `source .venv/bin/activate`

### 数据源

- **公拍网**(不登录可获取数据与图片):
  - 房产搜索列表: `https://s.gpai.net/sf/Search.do?at=376`
  - 即将开始: `...&restate=1` ; 正在拍卖: `...&restate=2`
  - 列表页 XPath 规则详见 `docs/初步信息.txt`
- **阿里资产**: 计划采用方式1 爬虫 / 方式2 API 两种方式

### 数据库

- PostgreSQL,连接信息见 `docs/初步信息.txt`,通过 `config.py` 读取环境变量配置。

## 运行方式

系统支持 **双通道运行**:

- **人工**: 直接运行 `scripts/` 下的独立脚本,例如 `python scripts/crawl_gpai.py --restate=2`
- **Agent**: 通过 `skills/` 中各技能的 `SKILL.md` 触发对应能力(渐进式加载: 元数据 → 指令 → 资源)

## 测试

- 运行测试: 进入虚拟环境后执行 `pytest tests/`
- 每个 skill 对应 `tests/test_<skill>.py`,含契约测试(输入/输出结构不变)

## 技术要点

- **Skill 不是纯代码**: 每个技能目录必须有 `SKILL.md`(YAML 元数据 `name`/`description` + Markdown 执行指令),Agent 靠元数据判断何时触发,正文 <5000 tokens,长资料拆到 `references/`
- **数据流**: 爬虫 → 原始数据/图片(assets) → 清洗 → 风险校验 → 入库(db) → 视频生成 → 发布
- **模型分层**: `db/listing.py`(ORM 持久化)与 `app/schemas/`(跨技能 DTO)分离
- **断点续跑**: assets 以 listing_id + 处理阶段做原子写,配合 DB 状态可中断恢复

## 进度

见 `reports/PROGRESS.md`

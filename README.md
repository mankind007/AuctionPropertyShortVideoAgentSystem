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
├── agent/               # 智能体核心层:model.py = DashScope(OpenAI 兼容)统一 LLM 客户端
├── app/                 # 应用主包:schemas(DTO)、orchestrator(多源编排)
├── scripts/             # 人工可直接运行的独立脚本(采集/进度/清理等 CLI)
├── skills/              # Agent 技能库:每个技能 = 目录 + SKILL.md(附 scripts/references/assets)
│   ├── gpai-crawler/    # 公拍网采集
│   ├── ali-assets-crawler/ # 阿里资产采集
│   ├── script-writer/   # 话术生成(规则素材库随机, 可选 --llm 润色)
│   ├── promo-image/     # 海报合成(读 data.script, 少图保底 4 张)
│   ├── video-compose/   # 静音视频拼接 + 视频/配音合成(mux_voice)
│   └── voice-tts/       # TTS 配音(edge-tts 免费, 逐角度 mp3)
├── db/                  # 数据库层:listing.py(ORM)、db.py(engine/session/upsert)
├── config.py            # 顶层配置:读 .env(DATABASE_URL、Ali* 等)
├── utils/               # 跨技能底层工具(浏览器封装、图片下载重试、网络重试、解析等)
├── tests/               # 单元/集成测试,每个 skill 对应测试(test_<skill>.py)
├── assets/              # 文件流水线:按 <source>/<item_id> 分桶 + 阶段分层
│   ├── fonts/           # 字体(标题/正文)
│   ├── 短视频宣传话术.csv # 话术素材库(角度/子主题/模板/宽松填充/备注)
│   └── {source}/{id}/   # imgs/原图 → posters/海报 → videos/静音与带配音视频 → voice/TTS mp3
├── reports/             # 进度与里程碑记录(PROGRESS.md)
├── docs/                # 调研与信息收集(数据源 XPath 规则等)
└── plans/               # 整体计划
```

## 环境要求

- Python 3.10(见 `.python-version`)
- 依赖见 `requirements.txt`:playwright、langchain、langgraph、pandas、SQLAlchemy、psycopg2-binary、Pillow、imageio-ffmpeg(捆绑 ffmpeg)、edge-tts、openai 等
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

- **人工**: 直接运行 `skills/*/scripts/` 下的独立脚本(带 `--help`),按流水线顺序:

```powershell
# 1) 采集(公拍网/阿里资产)
python scripts/crawl_gpai.py --restate=2
# 2) 话术(规则素材库; --llm 显式开启润色)
python skills/script-writer/scripts/generate_scripts.py --source gpai --all --limit 1000
# 3) 海报(读 data.script; 1图/2图自动保底扩到4张)
python skills/promo-image/scripts/compose.py --source gpai --all --limit 1000
# 4) 静音视频
python skills/video-compose/scripts/make_video.py --source gpai --all --limit 1000 --workers 4
# 5) TTS 配音(edge-tts 免费; 断点续传, 缺角度自动补)
python skills/voice-tts/scripts/tts_voice.py --source gpai --all --limit 1000
# 6) 视频+配音合成(海报段时长=对应音频时长, 声画对齐)
python skills/video-compose/scripts/mux_voice.py --source gpai --all --limit 1000

# 辅助: 进度查看 / 过期清理(DB+assets 同步删, 可反复跑)
python scripts/status.py [--watch]
python scripts/purge_expired.py [--execute] [--grace-hours 24]
```

- **Agent**: 通过 `skills/` 中各技能的 `SKILL.md` 触发对应能力(渐进式加载: 元数据 → 指令 → 资源)

所有步骤幂等可断点续跑: 已完成的默认跳过, 加 `--force` 强制重做。

## 测试

- 运行测试: 进入虚拟环境后执行 `pytest tests/`
- 每个 skill 对应 `tests/test_<skill>.py`,含契约测试(输入/输出结构不变)

## 技术要点

- **Skill 不是纯代码**: 每个技能目录必须有 `SKILL.md`(YAML 元数据 `name`/`description` + Markdown 执行指令),Agent 靠元数据判断何时触发,正文 <5000 tokens,长资料拆到 `references/`
- **数据流**: 爬虫 → 清洗入库(db) → 话术(script-writer, 写 `data.script`) → 海报(promo-image, 读稿写 `script_images`) → 静音视频(video-compose) → TTS(voice-tts, 逐角度 mp3) → 视频+配音(mux_voice, 声画对齐) → 发布(未实现)
- **话术/海报职责分离**: script-writer 只生成话术写 `data.script`;promo-image 只读 `data.script` 合成海报。话术与音频按"角度"组织(固定 8 个),与图片数量解耦
- **LLM 基座分层**: `agent/model.py` 是唯一 LLM 访问入口(DashScope OpenAI 兼容);具体任务只拼 prompt+校验+回退,默认纯规则,`--llm` 显式开启
- **模型分层**: `db/listing.py`(ORM 持久化)与 `app/schemas/`(跨技能 DTO)分离
- **断点续跑**: assets 以 `<source>/<item_id>` + 处理阶段做原子写,DB 存路径/状态作为事实源;TTS 缺角度自动补、过期数据可随时清理

## 进度

见 `reports/PROGRESS.md`

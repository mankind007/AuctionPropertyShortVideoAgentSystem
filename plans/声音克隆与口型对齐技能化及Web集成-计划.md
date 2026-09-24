# 声音克隆与口型对齐：技能化 + Web 集成 实施计划

日期: 2026-09-23  
状态: 待确认（未写代码）  
前置阅读: `AGENTS.md`、`docs/口型对齐_MuseTalk部署说明.md`、`skills/voice-tts/SKILL.md`、`skills/video-compose/SKILL.md`

---

## 0. 背景与目标

现状：口型对齐（MuseTalk）与声音克隆（Qwen3-TTS）均以「探路脚本」形态躺在 `tests/`；**MuseTalk 官方代码仓混放在 `models/lip-sync/MuseTalk`（models 应只放权重）**；两者未进入技能体系，Web 界面无入口。

目标：

1. **MuseTalk 代码仓迁出 `models/`**（权重仍留 `models/`，并登记 `AGENTS.md` 目录表）
2. 两者按 Agent Skills 规范落成 `skills/lip-sync`、`skills/voice-clone`
3. Web 页面可上传素材、触发任务、查看进度与成片
4. 不破坏既有 edge-tts 配音 → 海报视频 → mux 主链路

约束（来自 AGENTS.md）：

- 技能 = 目录 + `SKILL.md`（frontmatter 必填），可选 `scripts/ references/ assets/`
- 脚本必须能被人工直接运行：argparse、`--help`、清晰报错
- 每个 skill 对应 `tests/test_<skill>.py`，优先契约测试
- 双通道：人工 CLI 与 Agent 触发复用同一套 `skills/*/scripts/`
- 配置走 `.env` + `config.py`，本两能力不新增 API key

命名约定：计划类文件名**不带日期**，日期写在文件内（本文件即按此执行）。

---

## 1. 现状盘点

### 1.1 目录与体积

| 路径 | 内容 | 体积 | 判定 |
|------|------|------|------|
| `models/lip-sync/`（除 MuseTalk） | musetalkV15 / sd-vae / whisper / dwpose / face-parse-bisent | ~4.1 GB | **留**（权重，归属正确） |
| `models/lip-sync/MuseTalk/` | 官方**代码仓** + 内嵌 `s3fd.pth` | **104 MB / 122 文件**（s3fd≈86MB，纯代码≈18MB） | **迁出**（代码不该在 models） |
| `models/tts/` | Qwen3-TTS-12Hz-0.6B-Base | 2.34 GB | **留**（权重） |
| `tests/test_lipsync_musetalk.py` | 口型对齐端到端（已跑通，含 `--check`） | — | 收敛进技能 `scripts/` |
| `tests/test_qwen3_tts_clone.py` / `_simple.py` | 声音克隆重复两份 | — | 收敛为一个技能入口 |
| `docs/口型对齐_MuseTalk部署说明.md` | 部署与踩坑 500+ 行 | — | 宜作 skill `references/` |
| `.gitignore` `/models` | 整目录忽略 | — | 权重不入库；**代码迁出后需入库**（见 §2.1.3） |

`skills/` 现有 6 个技能，每个仅 2~5 个文件——**技能层保持轻量是既定事实**；104MB 官方仓属于「技能的第三方依赖代码」，放 `vendor/` 而非 `scripts/` 顶层，语义仍清晰。

MuseTalk 官方仓结构（迁移动对象）：

```
models/lip-sync/MuseTalk/
├── musetalk/          # 核心 Python 包（推理必需）
├── scripts/           # 官方 inference.py 等
├── configs/  data/    # 配置与示例数据
├── assets/            # ~6MB 示例素材
├── app.py  train.py   # 官方 Web/训练入口（本项目不用，可后裁）
├── s3fd 权重经固定相对路径加载: musetalk/utils/face_detection/detection/sfd/s3fd.pth
└── (junction) models → <repo>/models/lip-sync   ← ensure_junction() 自建
```

### 1.2 关键路径耦合（迁移动哪里要改哪里）

`tests/test_lipsync_musetalk.py`（未来 `skills/lip-sync/scripts/lipsync.py`）：

```python
LIPSYNC_DIR   = REPO_ROOT / "models" / "lip-sync"          # 权重根 —— 不变
MUSETALK_DIR  = LIPSYNC_DIR / "MuseTalk"                    # 代码根 —— 要改
ensure_junction(): mklink /J  {MUSETALK_DIR}/models  →  {LIPSYNC_DIR}   # 两端语义不变，link 位置随代码走
enter_musetalk_pkg(): os.chdir(MUSETALK_DIR); sys.path.insert(MUSETALK_DIR)
```

官方代码假定 **cwd = MuseTalk 仓根** 且 `./models/...` 能解析到权重 → **junction 必须继续跟代码仓走**，目标仍指向 `models/lip-sync`（绝对路径，脚本已如此实现）。

### 1.3 Web 既有模式（必须复用）

```
SKILL.md frontmatter ──> GET /api/skills（自动发现，无需注册清单）
TaskType 枚举 ──> db/models.py + alembic 枚举迁移
app/web/services/<name>.py  build_xxx_cmd()  ← CLI 参数与脚本严格对齐
app/web/services/registry.py  TaskType -> builder
app/web/api/skills.py  skill_name -> TaskType 映射 + 后台建 Task
app/web/templates/skills.html  按技能名渲染参数表单（当前 if-else 硬编码）
详情页 workflow  stages: script → poster → voice → video(→mux)
素材上传  POST /api/materials  已支持 image / audio（直接复用）
进度推送  GET /api/tasks/{id}/stream  SSE（skills.html 已用）
```

### 1.4 数据契约（既有）

- `data.script` — 8 角度话术
- `data.voice` — `{files:[{angle,file,duration}], full}`（edge-tts 写入）
- `data.video` / `data.video_voiced` — 静音片 / 配音片
- assets 按 `assets/<source>/<item_id>/<stage>/` 分桶

声音克隆若接入 voice 阶段，**必须写同一 `data.voice` 结构**，否则 mux/详情页全要分叉。

---

## 2. 决策点（请确认后再动代码）

### 2.1 MuseTalk 代码仓迁去哪？

`models/` 继续只放权重（`models/lip-sync/*` 权重 + `models/tts/`），已确认无异议。

**候选：**

| 方案 | 结构 | 优点 | 缺点 |
|------|------|------|------|
| A. 技能 `vendor/`（推荐） | `skills/lip-sync/vendor/MuseTalk/` | 代码与技能同居，自包含；`models/` 名实相符；换实现只换 vendor | 技能目录多一层；104MB 是否入 git 见 §2.1.3 |
| B. 顶层 `vendor/` 或 `third_party/` | `vendor/MuseTalk/` | 与 skills 解耦，多技能可共享同一官方仓 | 又造一个野生顶层目录，AGENTS 表要再加；与「能力=技能」的组织方式略脱节 |
| C. 留在 `models/` 只改名说明 | 不动 | 零迁移 | 与本次诉求矛盾，不考虑 |

**推荐 A**，目标结构：

```
models/                                # 仅权重，gitignore /models 不变
├── lip-sync/
│   ├── musetalkV15/  sd-vae/  whisper/  dwpose/  face-parse-bisent/
│   └── sfd/                            # 可选 Phase 2：从 MuseTalk 树挪出 s3fd.pth（见下）
└── tts/
    └── Qwen3-TTS-12Hz-0.6B-Base/

skills/lip-sync/
├── SKILL.md
├── scripts/
│   └── lipsync.py                      # 自 tests/test_lipsync_musetalk.py 迁入
├── vendor/
│   └── MuseTalk/                       # 官方仓整树迁入
│       └── models → junction → <repo>/models/lip-sync   （ensure_junction 自建，幂等）
└── references/
    └── 部署与调参.md                    # 自 docs/ 迁入，docs 留短桩

skills/voice-clone/
├── SKILL.md
└── scripts/
    └── clone_voice.py                  # 收敛两个 test_qwen3_tts_clone*.py
```

路径改动面（预期很小）：

| 符号 | 现值 | 新值 |
|------|------|------|
| `LIPSYNC_DIR` | `models/lip-sync` | **不变** |
| `MUSETALK_DIR` | `models/lip-sync/MuseTalk` | `skills/lip-sync/vendor/MuseTalk` |
| junction link | `{MUSETALK_DIR}/models` | 同左式（随 MUSETALK_DIR 自动变） |
| junction target | `LIPSYNC_DIR` | **不变** |

**s3fd.pth（≈86MB 权重）策略：**

- **Phase 1（推荐）**：随 MuseTalk 树整树移动，不改官方加载路径——一次 rename，零改码
- **Phase 2（可选）**：挪到 `models/lip-sync/sfd/`，改官方或包一层加载路径，使 vendor 内「纯代码、零权重」。收益是语义更干净，代价是碰第三方路径；**默认不做**

**需确认：选 A？**

#### 2.1.3 vendor 是否入 git？

| 选项 | 适用 |
|------|------|
| **入 git（推荐）** | 去掉 s3fd 后纯代码约 18MB + assets 6MB；本机 GitHub/HF 不稳（靠 gh-proxy），入库保证离线可装、版本钉死 |
| gitignore `vendor/` | 仓库更瘦；SKILL.md 必须写清 gh-proxy 克隆命令与 commit 钉扎；换机器要重新拉 |

推荐：**Phase 1 整树入 git（含 s3fd 也可，86MB 一次性成本）**；若介意体积，Phase 1 就把 s3fd 挪 `models/lip-sync/sfd/` 再入库（需多改一处加载路径，见上）。二选一即可。

**需确认：vendor 入 git 与否；s3fd 跟代码走还是进 models/sfd/。**

### 2.2 技能怎么划？

| 项 | 推荐 | 备选 |
|----|------|------|
| 口型对齐技能名 | `lip-sync` | `musetalk`（绑死实现） |
| 声音克隆技能名 | `voice-clone`（与 `voice-tts` 并列） | 并入 `voice-tts` 加 `--backend` |
| 克隆与 edge-tts 关系 | **两技能 + 同一 voice 阶段**，按参数选 backend | 合并（qwen/mmcv 重依赖与 edge-tts 轻依赖纠缠） |

**推荐独立 `voice-clone`**：依赖体量、GPU 需求、失败模式完全不同；两技能都产出同一 `data.voice`，mux 不感知来源。

### 2.3 Web 入口形态？

| 入口 | 是否做 | 说明 |
|------|--------|------|
| 技能管理页 `/skills` 自动出现 | **必做** | frontmatter 即被 `GET /api/skills` 扫到；补参数表单 |
| 新建「数字人工坊」`/studio` | **推荐做** | 口型对齐输入是「任意人物图+音频」，与房源弱绑定；克隆 ref 音频管理也适合放这 |
| 房源详情页 voice 加「克隆音色」 | **推荐 Phase 3** | 只改触发的 TaskType/参数，`data.voice` 结构不变 |
| 房源工作流加 `lipsync` 阶段 | **暂不做** | 房源图是房产不是人脸；批量「主持人数字人片」见 §5.4 选配 |
| 管线页 `/pipeline` 批量勾选 | **暂不做** | 同上 |

**需确认：/studio 独立页 —— 做 / 只做技能页？**

### 2.4 其它确认项

1. **MuseTalk 整仓迁 vendor**（推荐，先保真）还是只拷推理子集（`musetalk/` + `scripts/inference*` + configs，更瘦）？
2. **声音克隆接入 voice 阶段**：Phase 3 做不做？
3. **TaskType 枚举**：新增 `GENERATE_LIPSYNC`、`GENERATE_VOICE_CLONE` 需 alembic（Postgres 枚举加值）——可接受？

---

## 3. 目标目录结构（选定后的全景）

```
models/                                # 仅预训练权重（维持 gitignore /models）
├── lip-sync/
│   ├── musetalkV15/  sd-vae/  whisper/  dwpose/  face-parse-bisent/
│   └── sfd/                           # 仅当确认 s3fd 与代码分离时
└── tts/Qwen3-TTS-12Hz-0.6B-Base/

skills/
├── lip-sync/
│   ├── SKILL.md
│   ├── scripts/lipsync.py
│   ├── scripts/../vendor/MuseTalk/    # 实际为 skills/lip-sync/vendor/MuseTalk/
│   └── references/部署与调参.md
└── voice-clone/
    ├── SKILL.md
    └── scripts/clone_voice.py

tests/
├── test_lip_sync.py                   # 薄壳契约测试
└── test_voice_clone.py

app/web/
├── services/lip_sync.py               # build_lipsync_cmd()
├── services/voice_clone.py            # build_voice_clone_cmd()
├── services/registry.py
├── api/skills.py
└── templates/
    ├── skills.html                    # 两技能表单 + 建议 params schema 化
    └── studio.html                    # 新增：数字人工坊

db/models.py + migrations/             # TaskType 两个新值
docs/口型对齐_MuseTalk部署说明.md        # 改为指向 skills/lip-sync/references/ 的短桩
AGENTS.md                              # 目录表登记 models/（权重）、说明 vendor 约定
reports/PROGRESS.md                    # 每阶段追加
```

**删除/归档：**

- `models/lip-sync/MuseTalk` → 迁走后 models 下不再有代码仓
- `tests/test_lipsync_musetalk.py` → 逻辑迁 `skills/lip-sync/scripts/lipsync.py`，测试改薄壳
- `tests/test_qwen3_tts_clone.py`、`_simple.py` → 收敛进 `clone_voice.py`
- `.gitignore`：`/models` **保留**；若 vendor 不入库则加 `skills/lip-sync/vendor/`

---

## 4. 技能设计

### 4.1 `skills/lip-sync`

**SKILL.md frontmatter（示意）：**

```yaml
name: lip-sync
description: 静态人物图+音频 → MuseTalk V1.5 口型同步讲话视频，写 assets/lip_sync/ 或指定输出。何时触发: 数字人口播、人物说话视频、口型对齐、lipsync；触发关键词包括"口型"、"对口型"、"数字人"、"讲话视频"、"lip sync"。
```

**CLI（现有 argparse 平移，仅改 `MUSETALK_DIR`）：**

```bash
python skills/lip-sync/scripts/lipsync.py \
  --image assets/man1.jpg --audio assets/me.mp3 \
  --output assets/lip_sync/man1_me.mp4 \
  --upper-boundary-ratio 0.58

python skills/lip-sync/scripts/lipsync.py --check
```

**数据契约：**

| | |
|--|--|
| 输入 | `--image` 人物图；`--audio` 音频（可接 `assets/<source>/<id>/voice/*.mp3`） |
| 输出 | 默认 `assets/lip_sync/<stem>_me.mp4`；h264+aac，奇数尺寸已自动取偶 |
| DB | 默认不写；§5.4 批量数字人片再定义 `data.lipsync` |
| 幂等 | 输出已存在且非 `--force` 则跳过 |

**references/部署与调参.md：** 迁入现有文档（§6 调参、§7 踩坑、§11 A/B 数据）；`docs/` 留跳转桩。

**依赖（SKILL.md 必写，主 requirements 目前未收录）：**

```powershell
uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
  diffusers==0.30.2 opencv-python omegaconf soundfile librosa
# mmcv/mmdet/mmpose 轮子见 references/部署与调参.md §4
```

### 4.2 `skills/voice-clone`

**frontmatter（示意）：**

```yaml
name: voice-clone
description: Qwen3-TTS 参考音频声音克隆——ref_audio(+可选 ref_text) + 目标文本 → 克隆音色 wav/mp3，可作为 voice-tts 的品牌音色替代。何时触发: 声音克隆、克隆音色、用自己的声音配音；触发关键词包括"克隆"、"音色"、"Qwen TTS"、"克隆配音"。
```

**CLI（两模式收敛）：**

```bash
# 工坊：任意文本
python skills/voice-clone/scripts/clone_voice.py \
  --ref-audio "assets/汲总.mp3" --ref-text "..." \
  --text "这里是深圳市特资投资集团公司..." \
  --output assets/tts_test_output/clone.wav

# 懒人（x_vector_only）
python skills/voice-clone/scripts/clone_voice.py --ref-audio ... --text ... --x-vector-only

# 房源（Phase 3，与 voice-tts 同契约）
python skills/voice-clone/scripts/clone_voice.py --source gpai --item-id 52946
```

**数据契约：**

| 模式 | 输入 | 输出 |
|------|------|------|
| 工坊 | ref 音频 + 文本 | 指定 wav 路径，不写 DB |
| 房源 | `data.script` + ref 配置 | 与 voice-tts **完全相同**的 `data.voice` + `voice/*.mp3` |

**ref 音频（房源模式）：** 全局 `.env`/config `VOICE_CLONE_REF_AUDIO` → 房源级 `listing.data.voice_ref` 覆盖 → 都无则报错并提示回退 edge-tts。

**依赖：** `qwen-tts`（已装）+ `soundfile` + SoX；模型 `models/tts/Qwen3-TTS-12Hz-0.6B-Base`（**路径不变**）。

### 4.3 测试

| 文件 | 类型 | 断言 |
|------|------|------|
| `tests/test_lip_sync.py` | 契约 | CLI `--help`；`MUSETALK_DIR`/`LIPSYNC_DIR` 布局断言（代码在 skills、权重在 models）；`ensure_junction` 幂等；可选 `--check` |
| `tests/test_voice_clone.py` | 契约 | CLI `--help`；模型目录检查；`build_voice_clone_cmd` 与 argparse 参数名一致 |

默认 `pytest tests/` 不跑 GPU 端到端；端到端走人工/技能 CLI。

---

## 5. Web 集成设计

### 5.1 后端改动清单

| 文件 | 改动 |
|------|------|
| `db/models.py` | `GENERATE_LIPSYNC`、`GENERATE_VOICE_CLONE` |
| `db/migrations/...` | alembic 枚举加值（以现网 dialect 为准） |
| `app/web/services/lip_sync.py` | `build_lipsync_cmd(...)` |
| `app/web/services/voice_clone.py` | `build_voice_clone_cmd(...)` |
| `registry.py` | 注册两 builder |
| `api/skills.py` | `skill_to_type` 增 `"lip-sync"`, `"voice-clone"` |
| `services/workflow.py` | **仅当** §2.4-2 确认：voice 阶段按 `backend` 改投克隆 TaskType；stage key 仍为 `voice` |

### 5.2 前端改动清单

**A. `/skills`（必做）**

- `lip-sync`：人物图/音频下拉（复用 `GET /api/materials?type=image|audio`）、高级项折叠（ratio/bbox-shift）
- `voice-clone`：ref 音频、ref 文本、目标文本（或 item_id）、`x_vector_only`
- **建议同 PR 做 params schema 化**：`SKILL.md` frontmatter 扩 `params:` JSON Schema，`GET /api/skills` 透传，前端通用渲染，去掉 if-else

**B. `/studio` 数字人工坊（推荐）**

- Tab1 口型对齐：选/传图 + 音频 → 跑 `lip-sync` → `<video>` 预览下载
- Tab2 声音克隆：ref 音频 + 文本 → 跑 `voice-clone` → `<audio>` 预览；可「存入素材库」供房源 voice
- 进度复用 SSE；上传复用 `POST /api/materials`；`main.py` 路由 + `base.html` 导航

**C. 详情页（Phase 3，待确认）**

- 「配音方式：edge-tts / 克隆音色」+ ref 选择
- 触发 workflow `voice` 带 `backend`；`data.voice` 结构不变 → mux/列表零改动

### 5.3 时序（studio 口型对齐）

```
选图/音频 → POST /api/materials
  → POST /api/skills/lip-sync/run {image_path, audio_path, ratio}
  → Task(GENERATE_LIPSYNC) → build_lipsync_cmd → subprocess
  → GET /api/tasks/{id}/stream
  → 完成后按输出路径预览/下载
```

### 5.4 选配：批量「主持人数字人片」（默认不做）

固定 `LIPSYNC_HOST_IMAGE` + 每套 `data.script`/voice → 开头数字人口播段 → 与海报视频 concat → `data.lipsync_intro`。  
**不在 Phase 1–4**；技能与权重就位后属增量。

---

## 6. 实施阶段

### Phase 1 — 代码仓迁出 + 路径打通（行为不变，~2 小时）

1. 建 `skills/lip-sync/{scripts,references,vendor}/`
2. **整树移动** `models/lip-sync/MuseTalk` → `skills/lip-sync/vendor/MuseTalk`（同盘 rename）
3. 改 `MUSETALK_DIR` 一处常量（及 `required_weights` 等引用处）
4. 跑 `ensure_junction()`：`vendor/MuseTalk/models` → `models/lip-sync`
5. **决定 s3fd**：跟树走（默认）或挪 `models/lip-sync/sfd/` 并改加载
6. **决定 vendor 是否入 git**（§2.1.3）
7. `.gitignore` 按需加 `skills/lip-sync/vendor/`；`AGENTS.md` 目录表登记 `models/`=权重、说明 vendor
8. 验收：
   - `--check` exit=0
   - man2 端到端 1 条（现成命令）
   - `pytest tests/` 不红
   - `models/lip-sync/` 下**无** `MuseTalk` 目录

**回滚：** 反向 rename + 恢复常量。

### Phase 2 — 技能化（~半天）

1. `skills/lip-sync/SKILL.md` + `scripts/lipsync.py`（迁入，补 `--force`/幂等）
2. `skills/voice-clone/SKILL.md` + `scripts/clone_voice.py`（两测试收敛）
3. 部署文档 → `references/部署与调参.md` + docs 短桩
4. `tests/test_lip_sync.py`、`tests/test_voice_clone.py` 契约测试
5. 旧 tests 删或薄壳；`PROGRESS.md` 追加

### Phase 3 — Web 后端 + 详情页 voice 开关（~半天，待 §2.4-2）

1. TaskType + alembic
2. 两 builder + registry + skills 映射
3. （若确认）workflow voice `backend=edge|clone`
4. 详情页开关 + ref 选择
5. `build_*_cmd` 与 CLI 参数名一致性测试

### Phase 4 — 前端：技能页 + /studio（~1 日）

1. `skills.html` 两技能表单 + params schema 化
2. `studio.html` + 路由 + 导航
3. SSE、预览、素材下拉
4. 手工/Playwright 验收

### Phase 5 — 收尾

- 子 requirements / SKILL.md 依赖核对
- `AGENTS.md`、`README.md` 更新
- `PROGRESS.md` 分阶段追加
- （可选）§5.4 另开计划

**估时：** 2~3 个工作日（不含 §5.4）。

---

## 7. 测试与验收

| 级别 | 内容 | 何时 |
|------|------|------|
| 契约 | `pytest tests/test_lip_sync.py tests/test_voice_clone.py` | Phase 2+ |
| 回归 | `pytest tests/` | 每 Phase |
| CLI 冒烟 | `--help`、`--check` / 模型存在检查 | Phase 1–2 |
| E2E | man2→mp4；克隆短句→wav | Phase 1、4 |
| Web | 上传→跑→SSE→预览；详情页克隆→voice→mux | Phase 4 |
| 迁移 | alembic upgrade/downgrade 本地各一次 | Phase 3 |

验收口径：

1. `models/lip-sync/` **不含**代码仓；全仓 grep 无 `models/lip-sync/MuseTalk` 残留（历史 PROGRESS 除外）
2. `GET /api/skills` 含 `lip-sync`、`voice-clone`
3. `/skills` 可建任务看进度；`/studio`（若做）可完成两能力端到端
4. edge-tts → video → mux 回归通过
5. `AGENTS.md` 含 `models/`（权重）说明；两 `SKILL.md` frontmatter 合规

---

## 8. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 迁走后 cwd/junction 断 | `ensure_junction()` 随 `MUSETALK_DIR` 自动指对；Phase 1 强制 `--check` + E2E |
| s3fd 若挪 models 需改第三方路径 | 默认 Phase 1 跟树走，零改码 |
| vendor 104MB 入 git 膨胀 | 去 s3fd 后 ~24MB 可接受；或 gitignore + gh-proxy 克隆钉 commit（§2.1.3 二选一） |
| Postgres 枚举迁移 | additive 低风险；先本地演练 downgrade |
| 重依赖污染主 requirements | 保持技能级文档/子 requirements |
| skills.html 硬编码表单 | Phase 4 schema 化一次还债 |
| 6GB 卡两 GPU 任务并行 | TaskRunner 串行排队即可 |
| 克隆换 backend 破坏 mux | 锁死 `data.voice` 结构；契约测试断言 keys |

**回滚：** Phase 1 反向 rename；其后按 git 分段 revert（开工后按仓库惯例分 commit，本计划阶段不主动 commit）。

---

## 9. 待你拍板

1. MuseTalk 代码：**`skills/lip-sync/vendor/MuseTalk`**（推荐） / 顶层 `vendor/`？
2. **s3fd.pth**：Phase 1 跟代码树走（推荐，零改码） / 挪 `models/lip-sync/sfd/`？
3. **vendor 是否入 git**：入（推荐，离线稳） / gitignore+克隆脚本？
4. `/studio` 独立页：**做**（推荐） / 先只做技能页？
5. 详情页 voice 接克隆 backend：Phase 3 **做** / 暂缓？
6. MuseTalk **整仓**（推荐） / 只拷推理子集？
7. TaskType 新枚举 + alembic：**接受**（推荐） / 改 string 避开迁移？

确认后按 Phase 1 → 5 开工；每 Phase 更新 `reports/PROGRESS.md`。

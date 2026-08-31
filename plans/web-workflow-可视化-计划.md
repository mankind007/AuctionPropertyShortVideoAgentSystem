# 房源工作流可视化（单条视频生成流水线）实施计划

**创建日期**: 2026-08-30  
**状态**: ✅ 已完成并验收

## 目标

在房源详情页增加**工作流面板**：对已有采集素材的单个房源，直观展示
`话术 → 海报(横/竖) → 配音 → 视频(横/竖) → 合成配音版` 流水线状态，
支持逐阶段一键触发、实时进度、产物预览。

> 仅改 Web 层（`app/web/` 增量），不动 `scripts/`、`skills/`、`db/listing.py`、
> `agent/`、`app/schemas/`。触发复用现有 TaskRunner + registry 的 `--item-id` 单条能力。

## 阶段定义

| key | 名称 | 依赖 | DB 判定键 `data[...]` | 产物预览来源 |
|-----|------|------|----------------------|--------------|
| `script` | 话术 | 采集完成 | `script`(非空) | 文本（详情页已有 `#d-script`） |
| `poster` | 海报 | script | `script_images`(非空列表) | `assets/{src}/{id}/posters/*_h.png / *_v.png` |
| `voice` | 配音 | script | `voice`(非空) | `assets/{src}/{id}/voice/*.mp3` |
| `video` | 视频 | poster | `video`(非空) | `assets/{src}/{id}/videos/{id}_h.mp4 / _v.mp4` |
| `mux` | 合成配音版 | video + voice | `video_voiced`(非空) | `assets/{src}/{id}/videos/{id}_voiced_*.mp4` |

状态机：`pending`(未完成) → `running`(有进行中任务) → `success` / `failed`。
阶段依赖不满足时前端禁用按钮（灰置）。

## 后端实现

### 1. Schema（`app/web/schemas.py` 追加）

```python
class WorkflowStage(BaseModel):
    key: str            # script/poster/voice/video/mux
    name: str           # 中文名
    status: str         # done / pending / running / failed
    progress: int       # 0-100
    current_step: str
    can_run: bool       # 依赖是否满足
    task_id: Optional[int]
    error_message: Optional[str]
    previews: List[dict] = []   # {url, label, type(image/video/audio)}

class ListingWorkflow(BaseModel):
    listing_id: int
    source: str
    item_id: str
    title: Optional[str]
    stages: List[WorkflowStage]
```

### 2. 状态聚合服务（新文件 `app/web/services/workflow.py`）

- `get_listing_workflow(listing, db)`：
  - 按上表从 `listing.data` 判定各阶段 done/pending
  - 扫描 `assets/{source}/{item_id}/{stage}` 目录构建 previews（文件名规则见上表）
  - 查询该房源最近的进行中/失败任务（`Task.params.item_id == listing.item_id` 且 type 对应）填 running/failed 状态
- 预览 URL 复用 `/api/materials/asset/{source}/{item_id}/{stage}/{filename}` 下载接口

### 3. 接口（`app/web/api/listings.py` 追加，放在 `/{listing_id}` 具体路由之后）

- `GET /api/listings/{listing_id}/workflow` → `ListingWorkflow`
- `POST /api/listings/{listing_id}/workflow/run`，body `{stage: "script|poster|voice|video|mux"}`
  - 校验阶段依赖（上游 done 才允许跑），否则 400
  - 复用 `registry.build_command` 的 item_id 构建命令，创建 Task + BackgroundTasks 跑 `_run_task_bg`

### 4. stage → TaskType 映射（复用 registry builder，传入 item_id）

```python
STAGE_TYPE = {
    "script": TaskType.GENERATE_SCRIPT,
    "poster": TaskType.GENERATE_POSTER,
    "voice":  TaskType.GENERATE_TTS,
    "video":  TaskType.GENERATE_VIDEO,
    "mux":    TaskType.MUX_VIDEO,
}
```

## 前端实现（`app/web/templates/detail.html` + `static/css/style.css`）

详情页顶部插入"工作流"区块（`#workflow-panel`）：

- 5 张横向阶段卡片，箭头连接：话术 → 海报 → 配音 → 视频 → 合成配音版
- 卡片内容：阶段名、状态徽标、进度条(进行中)、产物缩略图（image/video/audio 预览）
- 每张卡片一个"运行"按钮：可跑且依赖满足则可点，否则灰置
- 点击预览打开现有素材 modal（复用 `/api/materials/asset/...` 带 token）
- 轮询：`setInterval` 每 3s 调 `GET /api/listings/{id}/workflow` 刷新状态（轻量，含最新 Task 进度）

## 测试

- `tests/test_web_workflow.py`：契约测试
  - GET workflow：对已完整处理的房源（如 ali/1065728759255）断言各阶段 done + previews 非空
  - POST run：非法 stage → 400；依赖不满足 → 400；合法 stage → 201 创建任务

## 验收

1. `pytest tests/` 全绿（原 167 + 新增）
2. Playwright 打开某房源详情页，工作流面板正确显示各阶段状态与产物
3. 点"配音"按钮，卡片转 running，完成后变 done 并出现音频预览

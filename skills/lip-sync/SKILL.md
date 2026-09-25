---
name: lip-sync
description: 静态人物图 + 音频生成口型同步讲话视频，双后端 MuseTalk V1.5（全图融合）/ IMTalker（单图直出 512x512 说话头口播）。何时触发：需要给主持人/数字人图片配音说话、做口型对齐、lip-sync、生成说话视频时；关键词：口型、lip sync、musetalk、imtalker、说话视频、数字人开口、人物讲话视频、口播。输入人物图片(jpg/png/webp)与音频(mp3/wav/m4a)，输出带音轨的 mp4。不适用：房产静物图（非人脸）、实时流式换嘴。
params: [{"name":"image","type":"string","label":"人物图片路径","required":true},{"name":"audio","type":"string","label":"音频路径","required":true},{"name":"output","type":"string","label":"输出mp4(可选)"},{"name":"backend","type":"string","label":"后端 musetalk|imtalker","default":"musetalk"},{"name":"max_seconds","type":"number","label":"限制音频秒数","default":0},{"name":"fps","type":"number","label":"FPS","default":25},{"name":"batch_size","type":"number","label":"Batch","default":2},{"name":"force","type":"boolean","label":"强制重跑","default":false},{"name":"upper_boundary_ratio","type":"number","label":"上边界比例(可选)"},{"name":"a_cfg_scale","type":"number","label":"IMTalker 音频CFG(可选)"},{"name":"nfe","type":"number","label":"IMTalker ODE步数(可选)"}]
---

# lip-sync（口型对齐）

静态人脸图 + 语音 → 口型同步讲话视频。双后端：

| backend | 模型 | 输出 | 适用 |
|---------|------|------|------|
| `musetalk`（默认） | MuseTalk V1.5 | 保留原图全幅构图 | 主持人全身/半身图，要保留原背景 |
| `imtalker` | IMTalker | 512×512 说话头特写 | 口播数字人特写，单图直出 |

## 何时用

- 主持人/数字人/口播人物图需要「开口说话」
- 用户说：口型对齐、lip sync、musetalk、imtalker、说话视频、人物讲话视频

**不用**：非人脸素材（法拍房源图等）、实时直播换嘴。

## 依赖

- **MuseTalk**：权重 `models/lip-sync/{musetalkV15,sd-vae,whisper,dwpose,face-parse-bisent}`；代码仓 `skills/lip-sync/vendor/MuseTalk`（入 git，`models` junction 自动建）
- **IMTalker**：权重 `models/lip-sync/IMTalker/{generator.ckpt,renderer.ckpt,wav2vec2-base-960h}` + torch hub 的 `2DFAN4/s3fd`；代码仓 `skills/lip-sync/vendor/IMTalker`（入 git，`checkpoints` junction 自动建）
- GPU：RTX 3060 6GB，MuseTalk 默认 `fp16 + batch=2`；IMTalker 必须 CUDA
- MuseTalk 依赖已装于 `.venv`（torch 2.6 / diffusers 0.30.2 / mmcv shim 见 references）；IMTalker 额外依赖 `torchdiffeq / timm / av`（已装，勿按上游 requirements 装，其 pin 与本项目冲突）

## 怎么跑

仓库根执行：

```powershell
# 体检(按 backend 分别体检)
.venv\Scripts\python.exe skills\lip-sync\scripts\lipsync.py --check
.venv\Scripts\python.exe skills\lip-sync\scripts\lipsync.py --check --backend imtalker

# MuseTalk 生成（输出默认 assets/lip_sync/<image>_<audio>.mp4）
.venv\Scripts\python.exe skills\lip-sync\scripts\lipsync.py --image path\face.png --audio path\vo.mp3

# IMTalker 生成（输出默认 assets/lip_sync/<image>_<audio>_imtalker.mp4）
.venv\Scripts\python.exe skills\lip-sync\scripts\lipsync.py --backend imtalker --image path\face.png --audio path\vo.mp3

# 强制重跑已存在输出
... --force
```

常用参数：`--max-seconds 8`、`--fps 25`、`--batch-size 2`、`--no-fp16`、`--device cpu|cuda:0`、`--upper-boundary-ratio 0.58`（MuseTalk）；`--a-cfg-scale 2`、`--nfe 10`、`--seed 42`（IMTalker）。

## 约定

- **输出契约**：mp4 = 输入音频时长对齐 + 音轨；MuseTalk 奇数尺寸自动 `scale=trunc(iw/2)*2`，IMTalker 固定 512×512/25fps
- **幂等**：输出已存在且 ≥1KB 时跳过，`--force` 覆盖；两个 backend 默认输出名不同（imtalker 加后缀），互不覆盖
- **失败不静默**：权重缺 → 打印下载提示并 exit 1；IMTalker 子进程非 0 退出码 → exit 1
- IMTalker 走子进程（`cwd=vendor/IMTalker` + `PYTHONPATH`），无 triton → `TORCH_COMPILE_DISABLE=1` 压回 eager
- 部署/调参/踩坑全文：`references/部署与调参.md`

## 测试

`tests/test_lip_sync.py`（契约：路径常量、`--check`/`--help`、权重清单、backend 分支）。

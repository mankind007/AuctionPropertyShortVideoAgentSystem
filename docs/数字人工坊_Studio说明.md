# 数字人工坊 `/studio` — 说明（2026-09-23）

独立于房源流水线的「任意图/音频 → 人物视频 / 克隆音色」页面。导航：`工坊`。

## 三个 Tab

| Tab | 输入 | 端点 | 产物 |
|-----|------|------|------|
| 口型对齐 | 人物图 + 音频 | `POST /api/skills/lip-sync/run` | `assets/lip_sync/*.mp4` |
| 声音克隆 | 参考音频 + 参考文本 + 目标文本 | `POST /api/skills/voice-clone/run` | `assets/voice_clone/*.wav` |
| 录音+ASR | 浏览器麦克风 | `POST /api/materials/asr/transcribe` | 转写文本（辅助填 ref_text） |

上传统一走 `POST /api/materials/upload`（`kind=image|audio`，落盘 `assets/<kind>/`，**不写 materials 表**）。

## 涉及哪些数据表？

| 操作 | 写表？ | 说明 |
|------|--------|------|
| 选文件上传 (`/api/materials/upload`) | **否** | 只写文件到 `assets/{image,audio}/`，返回绝对路径给技能用；**不插 `materials`** |
| 运行 lip-sync / voice-clone (`/api/skills/*/run`) | **是 → `tasks`** | 插入一条 `Task`（type=`generate_lipsync`/`generate_voice_clone`），后台子进程跑 |
| 任务进度 SSE (`/api/tasks/{id}/stream`) | 是（更新） | 更新 `tasks.progress/current_step/status/result` |
| 成片预览 (`/api/materials/studio/{kind}/{file}`) | **否** | 只读 `assets/lip_sync\|voice_clone/` 文件 |
| 录音转写 (`/api/materials/asr/transcribe`) | **否** | 临时文件 + openai-whisper，用完删 |
| 登录 | 是 → `users` | JWT + bcrypt |

**结论**：工坊**会碰 `tasks` 表**（每次运行技能插一条任务），**不碰 `listings` / `materials`**。素材管理页（`/materials`）那套 `materials`/`user_materials` 与工坊上传是两套路径。

## ASR 技术选型

- 包：**openai-whisper**（已装于 `.venv`，`whisper.load_model("base")`，首次会下 base 权重到用户缓存）。
- **不用** `models/lip-sync/whisper`：那是 MuseTalk 口型用的 encoder 权重（只有 config/pytorch_model/preprocessor，**缺 tokenizer**），HF `WhisperProcessor` 加载会炸；且 openai-whisper 自带完整 tokenizer/权重，无需复用。
- **ffmpeg**：本机常不在 PATH。`materials.py` 的 `_ensure_ffmpeg_on_path()` 把 `imageio-ffmpeg` 捆绑二进制硬链为同目录 `ffmpeg.exe` 并 prepend PATH，openai-whisper 子进程调 `ffmpeg` 即可成功。
- 若以后改走 HF transformers 复用 `models/lip-sync/whisper`，需补：
  ```powershell
  $env:HF_ENDPOINT="https://hf-mirror.com"
  .venv\Scripts\hf.exe download openai/whisper-tiny --local-dir models\lip-sync\whisper `
    --include "tokenizer.json" "vocab.json" "merges.txt" "tokenizer_config.json" "special_tokens_map.json"
  ```

## 录音权限

`navigator.mediaDevices.getUserMedia({audio:true})` — 浏览器每次页面弹窗确认，无需服务端权限；失败时前端显示「麦克风权限被拒绝或不可用」。

## 相关代码

- 页面：`app/web/templates/studio.html`
- 上传/ASR：`app/web/api/materials.py`（`/upload`、`/asr/transcribe`、`/studio/{kind}/{file}`）
- 技能触发：`app/web/api/skills.py` → `Task` + `registry.build_command`
- 口型脚本：`skills/lip-sync/scripts/lipsync.py`
- 克隆脚本：`skills/voice-clone/scripts/clone_voice.py`

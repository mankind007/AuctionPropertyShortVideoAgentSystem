---
name: voice-clone
description: Qwen3-TTS 声音克隆——用参考音频+参考文本克隆音色生成新语音。何时触发：需要用特定人的声音说话、克隆音色、voice clone、让主播/汲总声音读话术时；关键词：声音克隆、音色克隆、voice clone、Qwen3-TTS、用XX的声音、克隆声音。输入参考音频+参考文本+目标文本，输出 wav 或房源 data.voice。与 voice-tts(edge-tts) 并列：voice-tts 免费在线音色，voice-clone 本地克隆真人音色。
params: [{"name":"ref_audio","type":"string","label":"参考音频路径","required":true},{"name":"ref_text","type":"string","label":"参考文本(精确克隆)"},{"name":"text","type":"string","label":"目标文本","required":true},{"name":"output","type":"string","label":"输出wav(可选)"},{"name":"x_vector_only","type":"boolean","label":"x-vector模式(免ref_text)","default":false},{"name":"source","type":"string","label":"房源source(可选)"},{"name":"item_id","type":"string","label":"房源item_id(可选)"},{"name":"force","type":"boolean","label":"强制重跑","default":false},{"name":"check","type":"boolean","label":"只体检","default":false}]
---

# voice-clone（Qwen3-TTS 声音克隆）

本地 Qwen3-TTS-12Hz-0.6B-Base：给一段参考人声，克隆其音色朗读任意目标文本。

## 何时用

- 要用**特定真人音色**（主播/汲总等）说话术
- 关键词：声音克隆、音色克隆、voice clone、克隆声音、用XX的声音
- 不用：通用免费音色 → 走 `skills/voice-tts`（edge-tts）

## 依赖

- 权重：`models/tts/Qwen3-TTS-12Hz-0.6B-Base`（`.gitignore`，不入库）
- 包：`qwen-tts`、`soundfile`、`torch`（已装于 `.venv`）
- SoX 必须在 PATH（qwen-tts 依赖）；GPU 可选（bf16），CPU 慢但可用

## 怎么跑

```powershell
# 精确克隆（推荐：ref-audio + ref-text 对齐）
.venv\Scripts\python.exe skills\voice-clone\scripts\clone_voice.py `
  --ref-audio assets\汲总.mp3 `
  --ref-text "还没签，正在审他的合同和谈条件呢啊" `
  --text "这里是深圳市特资投资集团公司。法拍房购买有风险。" `
  --output assets\voice_clone\out.wav

# 懒人模式（只要参考音频，不用写 ref_text，质量略降）
... --x-vector-only

# 体检
... --check
```

## 数据契约

- 输入：`--ref-audio`（wav/mp3/m4a）+ `--ref-text`（精确模式）+ `--text`（目标）
- 输出：wav（`--output`，默认 `assets/voice_clone/<stem>.wav`）；结构与 voice-tts 对齐时由编排层写 `data.voice`
- 幂等：输出已存在且 ≥1KB 时跳过，`--force` 覆盖
- 失败不静默：模型目录缺 / ref 缺 → exit 1 + 明确提示

## 注意

- 参考音频 3~15s、单人、干净；ref_text 需与实际所说对齐
- 与 `voice-tts` 共用同一 `data.voice` 结构（Phase 3 Web 集成时统一）

## 测试

`tests/test_voice_clone.py`（契约：路径、`--help`/`--check`、权重清单）。

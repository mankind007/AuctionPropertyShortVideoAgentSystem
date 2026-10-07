# vendor 本地补丁清单 (PATCHES)

> `skills/lip-sync/vendor/` 下是**第三方代码仓**(MuseTalk / IMTalker)的原样副本。
> 本文件记录所有**对第三方源码的本地修改**, 用于:
> 1. 升级/重拉 vendor 时知道要重新应用哪些补丁;
> 2. 排查问题时快速区分"官方行为"与"本机适配行为"。
>
> **基线 commit**: `e7ac680`(与 origin/main 同步)。
> 提取补丁: `git diff e7ac680 -- skills/lip-sync/vendor/`
> 回滚单个补丁: `git checkout e7ac680 -- <文件路径>`(会回到官方实现, 本机可能重新 OOM/崩溃)

**约定**: 新增自有代码一律放 `skills/lip-sync/scripts/`(如 `face_restore.py`), 不塞进 vendor;
vendor 内只做"不改就跑不起来"的最小适配。

---

## 一、MuseTalk (`vendor/MuseTalk/`)

### M-1 中文路径图片读取 — `musetalk/utils/preprocessing.py::read_imgs`

| 项 | 内容 |
|---|---|
| 改动 | `cv2.imread(img_path)` → `cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_COLOR)`; 读不出抛 `RuntimeError` 而非返回 `None` |
| 原因 | Windows 下 `cv2.imread` 走窄字符 API, 中文路径(`assets\特朗普.jpg`)必返回 `None`, 下游 `inference_topdown(img.shape)` 报 `'NoneType' object has no attribute 'shape'`, 无明确报错 |
| 风险 | 无。`imdecode` 是官方推荐的 Windows 非 ASCII 路径写法, 与 Linux 行为一致 |
| 冲突概率 | 低(函数体一行的替换) |

### M-2 `.gitignore` 锚定修正 — `vendor/MuseTalk/.gitignore`

| 项 | 内容 |
|---|---|
| 改动 | `models/` → `/models/`(只忽略 MuseTalk 根目录的权重 junction) |
| 原因 | 不锚定的 `models/` 会忽略**任意层级**的 models 目录, 导致源码 `musetalk/models/{unet,vae,syncnet}.py` 从未入库 —— 克隆一份仓库会缺三个核心模型定义 |
| 副作用 | `musetalk/models/` 下的文件现在会被 git 看到。权重由顶层 `.gitignore` 的 `*.pth / *.pt / *.ckpt / *.safetensors / *.onnx / *.pkl / *.h5` 兜底忽略, 不会误入库(已 `git check-ignore` 验证 `s3fd.pth` 85MB 仍被忽略) |
| 冲突概率 | 中(上游 .gitignore 可能变)。升级后务必确认仍是 `/models/` |

---

## 二、IMTalker (`vendor/IMTalker/generator/generate.py`)

### I-1 mmap 权重加载 — 新增 `torch_load_cpu()`, 替换 2 处 `torch.load`

| 项 | 内容 |
|---|---|
| 位置 | `_load_models()`(renderer ckpt)、`_load_generator_weights()`(generator ckpt) |
| 改动 | 新增 `torch_load_cpu(path)`: 优先 `mmap=True`, 失败回退普通 `torch.load`; 环境变量 `IMTALKER_NO_MMAP=1` 可强制走普通加载(对照/排查用) |
| 原因 | `renderer.ckpt` 2023MB, 普通 `torch.load` 峰值 >4GB 提交额度, 15GB 内存本机稳定触发 native 崩溃 `0xC0000005`(无 Python traceback)。mmap 后按需分页, 且 `load_state_dict` / `param.copy_` 只读不改源 |
| 实测 | mmap-on 49/45s vs mmap-off 51/49s, **mmap 反而快约 6%**; 连续 3 次 E2E 均 exit=0 |
| 风险 | 低。若源 ckpt 被后续就地修改会受影响(官方推理路径不会写 ckpt) |
| 冲突概率 | 低(新增独立函数 + 两行替换) |

### I-2 逐帧 uint8 预分配 + 双缓冲流水线 — `InferenceAgent.decode_image()`

| 项 | 内容 |
|---|---|
| 改动 | 原实现把所有帧(fp32, 3MB/帧)堆在 GPU 再 `torch.stack` → 改为: 值域变换挪到 GPU(`clamp(-1,1)*255 → uint8`, D2H 带宽省 3/4) + 预分配 uint8 缓冲 + 双缓冲 pinned staging(各 0.75MB) + 独立 copy stream, 传输与下一帧 GPU 计算重叠; 持 `ref` 防 allocator 复用仍在传输的显存 |
| 原因 | 25 秒 625 帧需连续 1.83GB 显存, 6GB 卡必 OOM; 改后 **GPU 恒定 3019MB(与时长无关)**, RAM 降至 1/4 |
| 实测 | 10 秒音频 89-93s → 76-78s(**-15%**); 同输入同 seed 逐帧对比 `mean_abs=13.73` < 同版本自比 `14.83`, 差异落在 IMTalker 固有非确定性内, **无画质损失** |
| 行为变更 | 返回值由 fp32 `[-1,1]` 变为 **uint8**; 与 I-3 的 `save_video` dtype 分支配套 |
| 已知边界 | 返回的 `d_hat.squeeze()` 在 `T=1`(极短视频)时会退化成 `[C,H,W]`, 经 I-5 的 `post_enhance` reshape 会多一维。实际音频至少数十帧, 概率极低 |
| 冲突概率 | 中(整个函数体重写) |

### I-3 `save_video()` dtype 分支

| 项 | 内容 |
|---|---|
| 改动 | 已是 uint8 时跳过 `clamp(-1,1)*255` 转换; fp32 输入仍走原路径 |
| 原因 | 配合 I-2, 避免对已 uint8 数据再翻倍峰值 |
| 冲突概率 | 低 |

### I-4 letterbox 输入(非 crop 模式) — `DataProcessor.letterbox_to()` / `preprocess()`

| 项 | 内容 |
|---|---|
| 改动 | 新增 `letterbox_to()`: 等比缩放 + 居中填充到 512×512, 有效区宽高**向下取偶**(H.264/yuv420p 要求偶数, 否则 `avcodec_open2(libx264)` 直接失败); `preprocess()` 在非 crop 路径调用, 并把 `lb_box` / `orig_size` 带进数据流; 推理输出按 `lb_box` 裁掉填充 |
| 原因 | 直接 `transforms.Resize((512,512))` 会把非方图非等比压变形(1386×784 → 正方形, 人脸被压宽) |
| 已知问题(官方设计工况) | 黑边 padding 本身是 out-of-distribution(训练数据全是人脸占主体的 512×512)。**实测**黑边 AR-jump 6.35% / 边缘延展 7.60%, 而官方 `--crop` 仅 3.81% —— **全图 letterbox 输入对 IMTalker 固有更不稳, 填充方式救不回; 要稳就用 `--crop`** |
| 冲突概率 | 中 |

### I-5 输出后处理 — 新增 `post_enhance()` + 在推理出口调用

| 项 | 内容 |
|---|---|
| 改动 | 还原原图尺寸(消 letterbox 的 0.94x 缩放损失)+ `UnsharpMask(radius=2, percent=50, threshold=3)` 补生成柔化; 逐帧 PIL, ~1k 帧约 5-10s |
| 原因 | 生成输出固有柔化(脸锐度 ~195 vs 原图 ~500) |
| 注意 | **无条件生效**, 包括 `--crop` 模式(此时 `orig_size=None` → 只锐化不缩放)。若需要官方原始输出做对照, 需临时注释该调用 |
| 冲突概率 | 低 |

### I-6 中文路径参考图读取 — `DataProcessor.default_img_loader()`

| 项 | 内容 |
|---|---|
| 改动 | `cv2.imread(path)` → `cv2.imdecode(np.fromfile(path, ...))`, 读不出抛 `ValueError(f"无法读取参考图: {path}")` |
| 原因 | 同 M-1, 中文文件名返回 `None` 并抛 `cv2.error` |
| 冲突概率 | 低 |

### I-7 `face_alignment` 关闭 compile — `DataProcessor.__init__()`

| 项 | 内容 |
|---|---|
| 改动 | `FaceAlignment(..., flip_input=False, compile=False)` |
| 原因 | 本机无 `cl.exe`, `compile=True` 每次必失败回退 eager 且缓存存不了, 只产生噪音日志 |
| 实测 | **不提速**(86-92s vs 89-93s), 价值仅为日志干净 |
| 冲突概率 | 低 |

### I-8 `.gitignore` 锚定修正 — `vendor/IMTalker/.gitignore`

| 项 | 内容 |
|---|---|
| 改动 | `models/` → `/models/`、`checkpoints/` → `/checkpoints/` |
| 原因 | 同 M-2; 且根 `checkpoints` 是指向 `models/lip-sync/IMTalker` 的 junction, 必须继续忽略(已验证 `git check-ignore` 命中 `/checkpoints/`, junction 权重未入库) |
| 冲突概率 | 中 |

---

## 三、未改动 / 有意未改动

- `vendor/IMTalker/app.py`(Gradio 路径)**未打补丁**, 与 CLI(`generator/generate.py`)行为已分叉: letterbox、uint8 流水线、后处理只在 CLI 路径生效。Gradio 出图与 CLI 出图不可直接对比。
- **未做** B 方案 NVENC GPU 编码(唯一涉画质项, 确认不做, 仅占 5.5s/6%)、动态资源检测(收益主要在容错)。

---

## 四、升级 vendor 时的操作步骤

```bash
# 1. 升级前导出当前补丁(留底)
git diff e7ac680 -- skills/lip-sync/vendor/ > /tmp/vendor_patches_$(git rev-parse --short HEAD).diff

# 2. 替换 vendor 源码(保留本仓库 .gitignore 与 SKILL.md)

# 3. 逐条重打补丁: 优先级 I-1 > I-2/I-3 > I-6 > M-1 > 其余
#    (I-1 不打好会直接 0xC0000005; I-2/I-3 必须成对)

# 4. 验证
python skills/lip-sync/scripts/lipsync.py --check --backend imtalker
python skills/lip-sync/scripts/lipsync.py --check              # musetalk
pytest tests/ -q
```

补丁依据的实测数据见 `reports/PROGRESS.md` 2026-09-29 各条记录。

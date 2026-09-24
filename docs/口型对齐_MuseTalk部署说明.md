# MuseTalk V1.5 口型对齐 — 部署说明

文档已迁至技能目录（2026-09-23）：

- **运行入口**：`skills/lip-sync/scripts/lipsync.py`
- **完整方法与踩坑**：[`skills/lip-sync/references/部署与调参.md`](../skills/lip-sync/references/部署与调参.md)
- **技能规范**：[`skills/lip-sync/SKILL.md`](../skills/lip-sync/SKILL.md)
- **权重**（不入库）：`models/lip-sync/`
- **代码仓**：`skills/lip-sync/vendor/MuseTalk/`

```powershell
.venv\Scripts\python.exe skills\lip-sync\scripts\lipsync.py --check
.venv\Scripts\python.exe skills\lip-sync\scripts\lipsync.py --image assets\man1.jpg --audio assets\me.mp3
```

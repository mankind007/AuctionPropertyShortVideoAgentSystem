# Web 仪表盘实施计划

**创建日期**: 2026-08-30  
**更新日期**: 2026-08-30

## 核心确认事项

| 编号 | 决策点 | 确认结果 |
|------|--------|----------|
| 1 | 初始管理员 | 自动建表时创建：`username=admin`、`role=admin`、`password=admin666`（bcrypt 哈希存储） |
| 2 | 用户上传素材类型 | **仅图片和文案（文本/文档）**，音频可选，**不含视频**<br>MaterialType 枚举：`IMAGE`、`DOCUMENT`、`AUDIO`（可选） |
| 3 | 任务重试 | 单任务最大重试 3 次（`Task.max_retries=3`），失败后状态置 `FAILED`，人工在界面点「重跑」创建新任务 |
| 4 | TaskLog 存储 | **不单独建表**。任务日志改为：<br>• 运行时实时写入 `Task.current_step`、`Task.progress`、`Task.error_message`<br>• 完整 stdout/stderr 落文件：`reports/runs/task_{task_id}.log`<br>• 如需审计，直接读日志文件，不占数据库空间 |

---

## 目录结构（仅增量，现有目录完全不动）

```
app/
├── schemas/              # 现有
├── orchestrator.py       # 现有
├── web/                  # 【新增】
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── deps.py
│   ├── models.py         # User, Task, Material, UserMaterial（无 TaskLog）
│   ├── auth.py
│   ├── schemas.py        # Pydantic 模型
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── listings.py
│   │   ├── tasks.py
│   │   ├── materials.py
│   │   ├── pipeline.py
│   │   └── skills.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── task.py       # TaskRunner（subprocess + 文件日志）
│   │   ├── registry.py
│   │   ├── crawl.py
│   │   ├── script_gen.py
│   │   ├── tts.py
│   │   ├── poster.py
│   │   ├── video.py
│   │   ├── material.py
│   │   └── pipeline.py
│   ├── templates/
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── listings.html
│   │   ├── detail.html
│   │   ├── tasks.html
│   │   ├── materials.html
│   │   └── skills.html
│   └── static/
│       ├── css/style.css
│       └── js/*.js
db/
├── models.py             # 【新增】扩展模型
├── listing.py            # 现有
├── db.py                 # 现有
└── migrations/           # Alembic
config.py                 # 追加 JWT_SECRET 等
requirements.txt          # 追加依赖
.env                      # 追加 JWT_SECRET, ADMIN_INIT_PASSWORD=admin666
scripts/
├── init_web_db.py        # 【新增】自动建表+建初始 admin
assets/
└── users/                # 用户素材：user_id/{images,documents,audio}/
uploads/                  # 临时上传
tests/
├── test_web_*.py
```

---

## 数据模型（`db/models.py`）

```python
# 无 TaskLog 表
class User(Base):
    id, username, email, hashed_password, role(Enum: admin/user), is_active, created_at

class Task(Base):
    id, owner_id, type(Enum), status(Enum), params(JSON), result(JSON),
    progress(int), current_step(str), error_message(str),
    max_retries=3, retry_count=0,
    created_at, started_at, finished_at

class MaterialType(Enum):
    IMAGE = "image"
    DOCUMENT = "document"      # 文案/文档
    AUDIO = "audio"            # 可选

class Material(Base):
    id, name, type(Enum: IMAGE/DOCUMENT/AUDIO), file_path, file_size, mime_type, meta(JSON),
    uploader_id, is_public, tags(JSON), created_at

class UserMaterial(Base):
    user_id, material_id, permission(view/edit/admin), assigned_at, assigned_by
```

---

## 任务执行器（`app/web/services/task.py`）

```python
class TaskRunner:
    async def run(task: Task):
        task.status = RUNNING; task.started_at = now(); db.commit()
        log_file = REPORTS_DIR / f"task_{task.id}.log"
        with open(log_file, "w") as lf:
            proc = await asyncio.create_subprocess_exec(*cmd, stdout=lf, stderr=lf)
            # 实时读取 lf，解析进度关键字更新 task.progress/current_step
            await proc.wait()
        task.status = SUCCESS if proc.returncode==0 else FAILED
        task.finished_at = now(); task.progress = 100; db.commit()
```

---

## 依赖变更（`requirements.txt` 追加）

```
fastapi>=0.110
uvicorn[standard]>=0.29
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
python-multipart>=0.0.6
jinja2>=3.1
alembic>=1.13
aiofiles>=23.2
```

---

## 实施阶段（共 5 阶段，约 10-14 天）

| 阶段 | 交付物 | 关键文件数 | 预估 |
|------|--------|------------|------|
| **Phase 0** | 基础设施：模型、迁移、配置、初始化脚本 | 8 | 1-2 天 |
| **Phase 1** | 核心 API：认证、房源、任务、素材、管线、技能 | 14 | 2-3 天 |
| **Phase 2** | 业务服务：封装 scripts/skills、任务执行器 | 10 | 2-3 天 |
| **Phase 3** | 前端页面：登录、仪表盘、列表/详情、任务、素材、技能 | 16 | 3-4 天 |
| **Phase 4** | 管理员功能、部署文档、收尾 | 6 | 1-2 天 |

---

## 启动方式（无 Docker）

```bash
# 首次部署
alembic upgrade head
python scripts/init_web_db.py   # 建表 + 创建 admin/admin666

# 开发
uvicorn app.web.main:app --reload --port 8000

# 生产（自行选择进程管理器）
uvicorn app.web.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 现有代码零破坏

- `scripts/`、`skills/`、`agent/`、`utils/`、`db/listing.py`、`app/schemas/`、**完全不修改**
- Web 仅通过 `subprocess` 调用 `scripts/*.py`，或 `import skills.xxx.scripts` 复用函数
- 新模型独立在 `db/models.py`，通过 `db/__init__.py` 导出

---

## 待开发细节（Phase 中再细化）

1. `TaskRunner` 进度关键字解析规则（各脚本输出什么行算进度）
2. 素材上传大小限制、类型白名单（图片/文档/可选音频）、缩略图生成
3. 前端 SSE 重连策略、进度条动画
4. 管理员「用户管理」「素材分发」页面交互细节
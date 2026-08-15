# 项目进度记录

> 每完成一个里程碑或新技能,在此追加记录。格式:`[日期] 状态 - 内容`(状态: 进行中 / 已完成 / 阻塞)

## 2026-08-12

- [x] 已完成 - 项目骨架搭建: 创建 `scripts/`(人工独立运行入口)、`skills/`、`src/`、`tests/`、`utils/`、`assets/` 等目录
- [x] 已完成 - 梳理架构规范: Agent Skills 规范(SKILL.md 结构)、`src/models/`(ORM) + `src/schemas/`(DTO) 分层、assets 按拍品ID分桶
- [x] 已完成 - 生成 `AGENTS.md`(Agent 工作指引)与 `README.md`(项目说明)
- [x] 已完成 - **公拍网爬虫技能 `skills/gpai-crawler/`**: SKILL.md + scripts/crawler.py + references/xpath_rules.md
- [x] 已完成 - 人工 CLI 入口 `scripts/crawl_gpai.py`(--restate/--with-images/--save-json)
- [x] 已完成 - 契约测试 `tests/test_gpai_crawler.py`(10 个用例,全部通过)
- [x] 已完成 - 实测爬取: restate=1 共 74 条、restate=2 共 7 条(均为司法拍卖房产),详情页图片 8 张/条
- [x] 已完成 - 修复实测发现的差异: 价格标签(起拍价/变卖价/最新价)、时间标签(开始时间/预计结束)、评估价单位归一
- [x] 已完成 - 修复单页爬错: 页面有 2 个 main-col-list,只取第一个;加 PAGE_CAP=20 单页上限校验
- [x] 已完成 - 实现图片下载(--download),实测下载 20 条房源 97 张图片到 assets/{listing_id}/imgs/
- [x] 已完成 - 确认翻页触发滑块验证(反爬),当前仅爬第 1 页,批量翻页需人工/打码
- [ ] 待办 - `src/models/` ORM 实体定义(listing / image / voice / video / publish)
- [ ] 待办 - 阿里资产数据源调研(方式1爬虫 / 方式2 API)
- [ ] 待办 - 数据清洗(结构化入表 + 非结构化 AI/规则清洗)
- [ ] 待办 - 图片去水印(image-processor skill)
- [ ] 待办 - 图文成片(video-builder skill)
- [ ] 待办 - TTS 配音接入(tts skill)
- [ ] 待办 - 风险校验(risk-checker skill)
- [ ] 待办 - 音视频合成(video-merger skill)
- [ ] 待办 - 多平台自动发布(publisher skill)

## 2026-08-21 [已完成] - 公拍网采集范围收敛 + 采集时间戳

- 方案B落地: 只采集"即将开始"(restate=1),删除"正在拍卖"(restate=2)支持
  - `crawler.py`: 移除 `--restate` CLI 参数,`fetch_listings()` 固定 restate=1,删除 end_time 解析逻辑
  - `src/schemas/listing.py`: `GpaiListing` 移除 `end_time` 字段,新增 `crawled_at`(ISO 采集时间戳,入库/排重/审计用)
  - 同步更新: tests(16 通过)、SKILL.md、xpath_rules.md、scripts/crawl_gpai.py、observe_gpai_pagination.py
- 实测采集 1 页 20 条正常,总数 74

## 2026-08-15 [已完成] - 爬虫公共抽象 / 图片重试 / start_time / 验证码增强 / 单表去重入库

- 计划: `plans/2026-08-15-爬虫公共抽象与去重入库.txt`
- 公共抽象(带类型注解): `utils/parsing.py`(价格/时间/链接/标签)、`utils/browser.py`(UA/LAUNCH_ARGS/STEALTH_SCRIPT 增强版)、`utils/download.py`(3次重试+退避1/2/4s 并发下载)
  - ali/gpai 两爬虫删除本地重复副本改 import;gpai 的 download_images 同步切重试版
- 阿里 start_time 从列表页 `p.time-todo > span.value` 解析(`08月15日 10:00` → 补当年),12-31 23:55 后打印临界提醒;实测 120/120 填充
- 验证码 DOM 检测(列表+子页): `#nc_1__scale_text`/`#nc_1_nz1` + URL 双通道;登录每5分钟自动刷新、滑块随机5-10分钟刷新提示人工
- 图片下载: 每张重试 3 次、退避 1/2/4s;批 3-5 张并发(不足全下)
- 单表 PostgreSQL 去重: `models/listing.py`(顶层,UNIQUE(source,item_id) + data JSONB)、`src/config.py`(.env DATABASE_URL)、`src/db.py`(engine/session/upsert 容错降级)、`scripts/init_db.py`(建表);ali CLI 新增 `--db`
- 依赖: `pip install psycopg2-binary`
- 测试: 新增重试/start_time 解析用例,pytest 32 通过
- 待办: `.env` 填真实密码 → `python scripts/init_db.py` 建表 → `--db` 实测 upsert 去重

## 2026-08-15 [已完成] - 双源采集实测 + 滑块自动处理 + SQLAlchemy 入库打通

- **双源实测成功**(各 1 页):
  - 公拍网: `python scripts/crawl_gpai.py --pages 1` → 总数 76,解析 20 条(起拍价/评估价/开始时间/采集时间戳均有效),`--save-json` 落盘
  - 阿里: `python scripts/crawl_ali.py --category 住宅 --pages 1` → 声明 100,解析 120 条,start_time 120/120 有效
- **滑块自动处理**: `_try_auto_slide`(crawler.py)检测 `#nc_1_nz1` 后模拟人手拖动(缓动曲线+随机抖动/停顿)自动通过,1-2 次尝试,失败才转人工;列表页+子页共用
  - 新增契约测试 `test_dom_blocked_detects_slider`/`test_try_auto_slide_success`/`test_try_auto_slide_no_slider`,pytest 36 通过
- **SQLAlchemy 入库打通**:
  - `.env` 填真实密码(`1116lry`),创建数据库 `auction`,`python scripts/init_db.py` 建表成功
  - 表 `listings`: 主键 + `UNIQUE(source,item_id)` 唯一约束 + data JSONB
  - upsert 去重实测: 同一 `(source,item_id)` 插两次 → count=1 内容更新,测试数据已清理
  - 全程 SQLAlchemy(DeclarativeBase/engine/session),无原生 SQL 持久化

## 2026-08-15 [已完成] - 多源并行采集 + gpai 入库

- 新增 `scripts/crawl_all.py` 并行编排: 子进程同时启动公拍网 + 阿里两套爬虫,各持独立 Chromium/profile/登录态,互不阻塞
  - 参数: `--pages`(通用)、`--ali-pages/--gpai-pages`(独立)、`--ali-category`、`--download`、`--db`、`--headless`、`--skip-gpai/--skip-ali`
  - 修复 Windows 下 `Popen` 不能直接执行 `.py` → 前缀 `sys.executable`
- gpai crawler 新增 `--db`: 结果 upsert 进 PostgreSQL(与 ali 同模式、同表、`UNIQUE(source,item_id)` 去重)
- 实测 `python scripts/crawl_all.py --pages 1 --db`:
  - 两源并行成功,入库 ali=120 条、gpai=20 条,price/time/data(assets_dir)/status 字段完整
  - **重复跑一次去重验证**: count 仍 120+20,无重复记录
- 测试 36 全绿

## 2026-08-15 [已完成] - DB data 结构重构 + gpai 资产迁移 + 以 DB 为准断点续传

- **新 data 结构(DB + meta.json)**:
  - `data.images` = `[{url, file|null}]`(file=本地文件名,未下载 null)
  - 移除 `data.assets_dir`(路径改为可推导 `assets/{source}/{item_id}/`)、移除 `data.raw` 的 href/title(保留起拍/评估/开始时间审计文本)
  - gpai 资产由 `assets/{item_id}/` 迁至 `assets/gpai/{item_id}/`(与阿里对称);临时 `scripts/migrate_schema.py` 迁移 140 条 + 29 目录后已删除
  - ali 存量 images 为空的 58 条补 URL(file 仍 null 因本地无图);61 条回填 file;gpai 20 条 file 全部回填
- **断点续传以 DB 为准**:
  - `src/db.py::get_source_images(source)` → `{item_id: [{url, file}]}`
  - 两爬虫 `--skip-complete`: 本地图齐全跳过子页;缺文件用 DB URL 离线补下(不开浏览器)
  - **修复迁移引发的误判断**: file=null 时 `(dir / "")` 退化为目录本身 exists=True → 漏判,改为显式要求 `x.get("file") and exists`
- **编排代码移入 `src/orchestrator.py`**(build_commands/run_sources),`scripts/crawl_all.py` 变薄仅 argparse,支持 `--skip-complete`/`--only gpai|ali`
- 测试 39 全绿;真实回填验证两次 gpai `--pages 1 --download --skip-complete --db` 均正常
- 清理: 结束早前遗留的两个卡死 ali 爬虫进程(1:42 启动)

## 2026-08-15 [已完成] - category 列修复 + 历史回填

- **根因**: `AuctionListing` DTO 无 `category` 字段,入库 `row = l.to_dict()` 永远无该键 → DB `category` 全 NULL
- **正式代码**:
  - `src/schemas/listing.py::AuctionListing` 新增 `category: Optional[str] = None`
  - ali 两处构造(`_parse_listing`/`_fetch_category_impl`)传 `category=category`
  - gpai 两处构造传 `category="房产"`(公拍网类型统一为房产)
- **历史回填**(一次性 `scripts/backfill_category.py`,跑完已删): ali 120 条→「住宅」、gpai 20 条→「房产」
- 测试 39 全绿(新增 category 断言)

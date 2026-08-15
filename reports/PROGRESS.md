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

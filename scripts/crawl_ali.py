"""阿里资产房产爬虫 —— 人工 CLI 入口。

复用 skills/ali-assets-crawler/scripts/crawler.py 的实现,便于人工直接运行。
(skill 目录名带连字符,无法用 import 导入,故按文件路径加载)

示例:
    python scripts/crawl_ali.py                     # 住宅 2 页,有头(首次登录)
    python scripts/crawl_ali.py --category 住宅 商业 工业 其他 --pages 2
    python scripts/crawl_ali.py --category 住宅 --pages 0
    python scripts/crawl_ali.py --category 住宅 --pages 2 --headless
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_mod_path = PROJECT_ROOT / "skills" / "ali-assets-crawler" / "scripts" / "crawler.py"
_spec = importlib.util.spec_from_file_location("ali_crawler", _mod_path)
_crawler = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_crawler)


if __name__ == "__main__":
    sys.exit(_crawler.main())
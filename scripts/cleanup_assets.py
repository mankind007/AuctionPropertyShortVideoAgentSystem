import os
import shutil
from pathlib import Path
from db import session_scope
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALI_DIR = PROJECT_ROOT / "assets" / "ali"
GPAI_DIR = PROJECT_ROOT / "assets" / "gpai"

# DB 里的 item_id
with session_scope() as s:
    ali_db = set(r[0] for r in s.execute(text("SELECT item_id FROM listings WHERE source='ali'")).fetchall())
    gpai_db = set(r[0] for r in s.execute(text("SELECT item_id FROM listings WHERE source='gpai'")).fetchall())

# assets 目录的 item_id
ali_assets = set(os.listdir(ALI_DIR))
gpai_assets = set(os.listdir(GPAI_DIR))

# 不在 DB 里的
ali_not_in_db = ali_assets - ali_db
gpai_not_in_db = gpai_assets - gpai_db

print(f"ali: 将删除 {len(ali_not_in_db)} 个目录")
print(f"gpai: 将删除 {len(gpai_not_in_db)} 个目录")

# 删除
for item_id in ali_not_in_db:
    path = ALI_DIR / item_id
    if path.is_dir():
        shutil.rmtree(path)

for item_id in gpai_not_in_db:
    path = GPAI_DIR / item_id
    if path.is_dir():
        shutil.rmtree(path)

print("删除完成")

# 验证
ali_remain = set(os.listdir(ALI_DIR))
gpai_remain = set(os.listdir(GPAI_DIR))
print(f"ali 剩余: {len(ali_remain)}")
print(f"gpai 剩余: {len(gpai_remain)}")
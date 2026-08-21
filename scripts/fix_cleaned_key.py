"""修复: 把 data 里的 __cleaned 替换为 _cleaned"""
from db import session_scope, upsert_listing
from sqlalchemy import text
import json

def fix_key(obj, old_key, new_key):
    if isinstance(obj, dict):
        if old_key in obj:
            obj[new_key] = obj.pop(old_key)
        for v in obj.values():
            fix_key(v, old_key, new_key)
    elif isinstance(obj, list):
        for item in obj:
            fix_key(item, old_key, new_key)

with session_scope() as s:
    rows = s.execute(text("SELECT item_id, source, data FROM listings")).fetchall()
    fixed = 0
    for item_id, source, data in rows:
        if data and "__cleaned" in json.dumps(data):
            fix_key(data, "__cleaned", "_cleaned")
            upsert_listing({"item_id": item_id, "source": source, "data": data})
            fixed += 1
    print(f"已修复: {fixed} 条")
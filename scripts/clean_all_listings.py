"""增量全量清洗: 重新清洗所有记录，按「是否发生变化」决定写入。

- 已为「中文键 schema」且 description 未提供新增字段的记录, 经 clean_listing_data 后
  JSON 无变化 -> 跳过(不写库, 避免重复处理已清洗数据)
- 缺失 _core / 仍含旧英文键 / 可从小结描述补充新字段的记录 -> 清洗并写入
"""
from db import session_scope, upsert_listing
from sqlalchemy import text
from utils.description import clean_listing_data
import json

# 旧版英文 core 键集合(用于识别「尚未迁移」的记录)
OLD_CORE_KEYS = {
    "area", "area_inner", "area_land", "layout", "orientation", "floor",
    "total_floors", "build_year", "price", "property_cert", "property_type",
    "structure", "location", "community", "owner", "arrears", "elevator",
    "occupancy", "decoration", "tax", "mortgage", "seizure", "coownership",
    "right_source",
}


def is_already_new_schema(data: dict) -> bool:
    """_core 已存在且不含任何旧英文键 -> 视为已迁移, 否则需要重洗。"""
    core = data.get("_core")
    if not core:
        return False
    return not any(k in core for k in OLD_CORE_KEYS)


with session_scope() as s:
    rows = s.execute(text("SELECT item_id, source, data FROM listings")).fetchall()

total = len(rows)
print(f"总记录: {total}")
updated = 0
skipped = 0
for item_id, source, data in rows:
    if not data:
        continue
    # 已迁移且无可补充新字段 -> 跳过(!= 仍需跑一次确认无变化, 但不写库)
    if is_already_new_schema(data):
        cleaned = clean_listing_data(dict(data))
        if json.dumps(cleaned, ensure_ascii=False, sort_keys=True) == \
           json.dumps(data, ensure_ascii=False, sort_keys=True):
            skipped += 1
            continue
    cleaned = clean_listing_data(dict(data))
    cleaned_str = json.dumps(cleaned, ensure_ascii=False, sort_keys=True)
    data_str = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if cleaned_str != data_str:
        upsert_listing({"item_id": item_id, "source": source, "data": cleaned})
        updated += 1
print(f"已更新: {updated} 条, 跳过(已清洗无变化): {skipped} 条")

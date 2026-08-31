"""素材服务：文件保存、缩略图生成等。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PIL import Image

from app.web.config import get_settings


settings = get_settings()
UPLOAD_ROOT = Path(settings.UPLOAD_DIR)


def generate_image_thumbnail(file_path: Path, max_size: tuple[int, int] = (300, 300)) -> Optional[Path]:
    """为图片生成缩略图，返回缩略图路径。"""
    try:
        thumb_dir = file_path.parent / ".thumbs"
        thumb_dir.mkdir(exist_ok=True)
        thumb_path = thumb_dir / f"{file_path.stem}_thumb{file_path.suffix}"

        with Image.open(file_path) as img:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            img.save(thumb_path, quality=85)
        return thumb_path
    except Exception:
        return None


def get_file_url(relative_path: str) -> str:
    """获取素材访问 URL（前端用）。"""
    return f"/api/materials/download/{relative_path}"


def get_file_size(relative_path: str) -> int:
    """获取文件大小。"""
    full_path = UPLOAD_ROOT / relative_path
    if full_path.exists():
        return full_path.stat().st_size
    return 0


def delete_file(relative_path: str) -> bool:
    """删除文件及缩略图。"""
    try:
        full_path = UPLOAD_ROOT / relative_path
        if full_path.exists():
            full_path.unlink()
        # 删除缩略图
        thumb_dir = full_path.parent / ".thumbs"
        thumb_path = thumb_dir / f"{full_path.stem}_thumb{full_path.suffix}"
        if thumb_path.exists():
            thumb_path.unlink()
        return True
    except Exception:
        return False
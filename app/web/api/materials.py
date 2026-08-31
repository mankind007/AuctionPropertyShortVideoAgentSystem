"""素材接口：上传、列表、下载、分发、删除。"""
from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from db import session_scope
from db.models import Material, MaterialType, UserMaterial, User
from app.web.config import get_settings
from app.web.deps import get_db, get_current_user, get_pagination
from app.web.schemas import MaterialOut, MaterialCreate, MaterialDistribute, PaginatedMaterials


router = APIRouter(prefix="/materials", tags=["素材"])

settings = get_settings()
UPLOAD_ROOT = Path(settings.UPLOAD_DIR)
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_DOC_TYPES = {"text/plain", "application/pdf", "application/msword",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
ALLOWED_AUDIO_TYPES = {"audio/mpeg", "audio/wav", "audio/ogg", "audio/mp3"}

MAX_FILE_SIZE = settings.UPLOAD_MAX_MB * 1024 * 1024


def _validate_file(file: UploadFile, material_type: MaterialType) -> None:
    if file.size and file.size > MAX_FILE_SIZE:
        raise HTTPException(413, f"文件过大，最大 {settings.UPLOAD_MAX_MB}MB")
    if material_type == MaterialType.IMAGE and file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "不支持的图片格式")
    if material_type == MaterialType.DOCUMENT and file.content_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, "不支持的文档格式")
    if material_type == MaterialType.AUDIO and file.content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(400, "不支持的音频格式")


def _save_file(file: UploadFile, user_id: int, material_type: MaterialType) -> tuple[str, int]:
    """保存文件，返回 (相对路径, 文件大小)。"""
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if not ext:
        ext = {MaterialType.IMAGE: ".jpg", MaterialType.DOCUMENT: ".txt", MaterialType.AUDIO: ".mp3"}[material_type]
    filename = f"{uuid.uuid4().hex}{ext}"
    user_dir = UPLOAD_ROOT / f"user_{user_id}" / material_type.value
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    file_size = file_path.stat().st_size
    # 返回相对 uploads/ 的路径
    rel_path = file_path.relative_to(UPLOAD_ROOT).as_posix()
    return rel_path, file_size


@router.post("", response_model=MaterialOut, status_code=201)
async def upload_material(
    file: UploadFile = File(...),
    name: str = "",
    type: str = "image",
    tags: str = "",
    is_public: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """上传素材。"""
    try:
        mat_type = MaterialType(type)
    except ValueError:
        raise HTTPException(400, "不支持的素材类型")

    if not name:
        name = file.filename or "未命名素材"

    _validate_file(file, mat_type)

    rel_path, file_size = _save_file(file, current_user.id, mat_type)

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    material = Material(
        name=name,
        type=mat_type,
        file_path=rel_path,
        file_size=file_size,
        mime_type=file.content_type,
        meta={},
        uploader_id=current_user.id,
        is_public=is_public,
        tags=tag_list,
    )
    db.add(material)
    db.commit()
    db.refresh(material)

    # 创建上传者自己的关联
    um = UserMaterial(
        user_id=current_user.id,
        material_id=material.id,
        permission="admin",
        assigned_by=current_user.id,
    )
    db.add(um)
    db.commit()

    return material


@router.get("", response_model=PaginatedMaterials)
def list_materials(
    type: Optional[str] = Query(None),
    mine_only: bool = Query(False),
    pagination=Depends(get_pagination),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """素材列表：mine_only=True 只看自己的（含分发给自己的），False 看公开+自己的。"""
    query = db.query(Material)
    if mine_only:
        # 通过 user_materials 关联查询
        query = query.join(UserMaterial, Material.id == UserMaterial.material_id).filter(
            UserMaterial.user_id == current_user.id
        )
    else:
        # 公开素材 + 自己上传的 + 分发给自己的
        query = query.filter(
            (Material.is_public == True)
            | (Material.uploader_id == current_user.id)
            | Material.id.in_(
                db.query(UserMaterial.material_id).filter(UserMaterial.user_id == current_user.id)
            )
        )
    if type:
        query = query.filter(Material.type == type)
    total = query.count()
    query = query.order_by(desc(Material.created_at))
    items = query.offset(pagination.offset).limit(pagination.limit).all()
    return PaginatedMaterials(
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
        items=items,
    )


# ─── assets/ 目录扫描 ───

ASSETS_ROOT = Path(__file__).resolve().parents[3] / "assets"

# 文件扩展名 -> (type, mime)
_EXT_MAP = {
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".webp": ("image", "image/webp"),
    ".gif": ("image", "image/gif"),
    ".mp3": ("audio", "audio/mpeg"),
    ".wav": ("audio", "audio/wav"),
    ".ogg": ("audio", "audio/ogg"),
    ".mp4": ("video", "video/mp4"),
    ".csv": ("document", "text/csv"),
    ".txt": ("document", "text/plain"),
    ".json": ("document", "application/json"),
}

# 子目录名 -> stage 标签
_STAGE_MAP = {
    "imgs": "imgs",
    "posters": "posters",
    "videos": "videos",
    "voice": "voice",
}


def _scan_assets(source: str | None = None, stage: str | None = None, type_filter: str | None = None) -> list[dict]:
    """扫描 assets/ 目录，返回文件列表（dict 格式兼容 MaterialOut）。"""
    if not ASSETS_ROOT.exists():
        return []

    results = []
    asset_id = -1  # 负数 ID，避免与 materials 表冲突

    for source_dir in sorted(ASSETS_ROOT.iterdir()):
        if not source_dir.is_dir():
            continue
        src_name = source_dir.name
        if source and src_name != source:
            continue
        if src_name not in ("gpai", "ali"):
            continue

        for listing_dir in sorted(source_dir.iterdir()):
            if not listing_dir.is_dir():
                continue
            listing_id = listing_dir.name

            for stage_dir_name in sorted(_STAGE_MAP.keys()):
                if stage and stage_dir_name != stage:
                    continue
                stage_dir = listing_dir / stage_dir_name
                if not stage_dir.exists():
                    continue

                for f in sorted(stage_dir.iterdir()):
                    if not f.is_file():
                        continue
                    ext = f.suffix.lower()
                    if ext not in _EXT_MAP:
                        continue
                    ftype, mime = _EXT_MAP[ext]
                    if type_filter and ftype != type_filter:
                        continue

                    rel_path = f.relative_to(ASSETS_ROOT).as_posix()
                    file_size = f.stat().st_size

                    tags = [src_name, stage_dir_name]
                    if stage_dir_name == "posters":
                        if "_h." in f.name:
                            tags.append("横版")
                        elif "_v." in f.name:
                            tags.append("竖版")
                    elif stage_dir_name == "videos":
                        if "_voiced" in f.name:
                            tags.append("配音版")
                        if "_h." in f.name:
                            tags.append("横版")
                        elif "_v." in f.name:
                            tags.append("竖版")

                    results.append({
                        "id": asset_id,
                        "name": f.name,
                        "type": ftype,
                        "source": src_name,
                        "listing_id": listing_id,
                        "stage": stage_dir_name,
                        "file_path": rel_path,
                        "file_size": file_size,
                        "mime_type": mime,
                        "tags": tags,
                        "is_public": True,
                        "meta": {},
                        "uploader_id": 0,
                        "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })
                    asset_id -= 1

    return results


@router.get("/scan")
def scan_assets(
    source: str | None = Query(None),
    stage: str | None = Query(None),
    type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=10000),
    current_user=Depends(get_current_user),
):
    """扫描 assets/ 目录，返回管线产出的素材文件。"""
    all_files = _scan_assets(source=source, stage=stage, type_filter=type)
    total = len(all_files)
    start = (page - 1) * page_size
    items = all_files[start : start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/asset/{source}/{listing_id}/{stage}/{filename}")
def download_asset(
    source: str,
    listing_id: str,
    stage: str,
    filename: str,
    current_user=Depends(get_current_user),
):
    """下载 assets/ 目录中的文件。"""
    if stage not in _STAGE_MAP:
        raise HTTPException(400, f"无效的 stage: {stage}")
    file_path = ASSETS_ROOT / source / listing_id / stage / filename
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    ext = file_path.suffix.lower()
    mime = _EXT_MAP.get(ext, ("document", "application/octet-stream"))[1]
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=mime,
    )


# ─── 以下路由必须放在 /scan 和 /asset 之后，避免被 /{material_id} 吞掉 ───
def get_material(material_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """获取素材详情。"""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(404, "素材不存在")
    # 权限检查
    if not material.is_public and material.uploader_id != current_user.id:
        has_access = db.query(UserMaterial).filter(
            UserMaterial.material_id == material_id,
            UserMaterial.user_id == current_user.id
        ).first()
        if not has_access:
            raise HTTPException(403, "无权访问")
    return material


@router.get("/{material_id}/download")
def download_material(material_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """下载素材文件。"""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(404, "素材不存在")
    if not material.is_public and material.uploader_id != current_user.id:
        has_access = db.query(UserMaterial).filter(
            UserMaterial.material_id == material_id,
            UserMaterial.user_id == current_user.id
        ).first()
        if not has_access:
            raise HTTPException(403, "无权下载")
    file_path = UPLOAD_ROOT / material.file_path
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(
        path=file_path,
        filename=material.name + Path(material.file_path).suffix,
        media_type=material.mime_type or "application/octet-stream",
    )


@router.post("/{material_id}/distribute", status_code=204)
def distribute_material(
    material_id: int,
    req: MaterialDistribute,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """分发素材给用户（仅上传者或 admin）。"""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(404, "素材不存在")
    if material.uploader_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(403, "仅上传者或管理员可分发")

    for uid in req.user_ids:
        user = db.query(User).filter(User.id == uid).first()
        if not user:
            continue
        um = db.query(UserMaterial).filter(
            UserMaterial.material_id == material_id,
            UserMaterial.user_id == uid
        ).first()
        if um:
            um.permission = req.permission
            um.assigned_at = datetime.now()
            um.assigned_by = current_user.id
        else:
            um = UserMaterial(
                user_id=uid,
                material_id=material_id,
                permission=req.permission,
                assigned_by=current_user.id,
            )
            db.add(um)
    db.commit()


@router.delete("/{material_id}", status_code=204)
def delete_material(material_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """删除素材（仅上传者或 admin）。"""
    material = db.query(Material).filter(Material.id == material_id).first()
    if not material:
        raise HTTPException(404, "素材不存在")
    if material.uploader_id != current_user.id and current_user.role.value != "admin":
        raise HTTPException(403, "仅上传者或管理员可删除")
    # 删除文件
    file_path = UPLOAD_ROOT / material.file_path
    if file_path.exists():
        file_path.unlink()
    # 删除关联记录（级联会自动删 user_materials）
    db.delete(material)
    db.commit()
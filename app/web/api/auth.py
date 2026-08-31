"""认证接口：登录、刷新、获取当前用户信息。"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, status
from sqlalchemy.orm import Session

from db import session_scope
from db.models import User
from app.web.auth import create_access_token, verify_password, hash_password
from app.web.deps import get_db, get_current_user
from app.web.schemas import Token, UserCreate, UserOut, UserUpdate


router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=Token)
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    """用户名/密码登录，返回 JWT。"""
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(
        data={"sub": user.id},
        expires_delta=timedelta(minutes=1440),
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/refresh", response_model=Token)
def refresh_token(current_user: User = Depends(get_current_user)):
    """刷新 access token。"""
    access_token = create_access_token(data={"sub": current_user.id})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。"""
    return current_user


# 管理员用户管理（仅 admin）
@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(lambda u=Depends(get_current_user): u if u.role.value == "admin" else (_ for _ in ()).throw(HTTPException(403, "Admin only"))),
):
    """创建用户（仅 admin）。"""
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(400, "用户名已存在")
    user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hash_password(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(lambda u=Depends(get_current_user): u if u.role.value == "admin" else (_ for _ in ()).throw(HTTPException(403, "Admin only"))),
):
    """用户列表（仅 admin）。"""
    return db.query(User).all()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(lambda u=Depends(get_current_user): u if u.role.value == "admin" else (_ for _ in ()).throw(HTTPException(403, "Admin only"))),
):
    """更新用户（仅 admin）。"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    if user_in.email is not None:
        user.email = user_in.email
    if user_in.role is not None:
        from db.models import UserRole
        user.role = UserRole(user_in.role)
    if user_in.is_active is not None:
        user.is_active = user_in.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除用户（仅 admin，不能删自己）。"""
    if current_user.role.value != "admin":
        raise HTTPException(403, "Admin only")
    if current_user.id == user_id:
        raise HTTPException(400, "不能删除自己")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")
    db.delete(user)
    db.commit()
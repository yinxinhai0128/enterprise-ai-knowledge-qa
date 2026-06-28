"""账号密码认证接口。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.auth import JWT_ALGORITHM
from app.core.database import get_session
from app.core.limits import LimitedAdminAuth, QAAuth
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------- 密码哈希 ----------
import bcrypt as _bcrypt


def _hash_pwd(pwd: str) -> str:
    return _bcrypt.hashpw(pwd.encode(), _bcrypt.gensalt()).decode()


def _verify_pwd(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------- JWT 签发 ----------
_DEFAULT_EXPIRE_SECONDS = 86400  # 1 天


def _issue_token(*, username: str, tenant_id: str, roles: list[str]) -> str:
    """签发与现有验签完全兼容的 JWT。"""
    secret = settings.auth_jwt_secret.get_secret_value()
    expire_seconds = getattr(settings, "auth_jwt_expire_seconds", _DEFAULT_EXPIRE_SECONDS)
    now = datetime.now(timezone.utc)
    claims = {
        "sub": username,
        "tenant_id": tenant_id,
        "roles": roles,
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": now,
        "exp": now + timedelta(seconds=expire_seconds),
    }
    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


# ---------- 请求/响应模型 ----------

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._@-]+$")
    password: str = Field(min_length=8, max_length=256)
    tenant_id: str = Field(min_length=1, max_length=128)
    roles: list[str] = Field(default_factory=list)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=256)


# ---------- 端点 ----------

@router.post("/login", response_model=LoginResponse, summary="账号密码登录")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_session),
) -> LoginResponse:
    user = (
        await db.execute(
            select(User).where(User.username == req.username, User.is_active == True)  # noqa: E712
        )
    ).scalar_one_or_none()

    if user is None or not _verify_pwd(req.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = _issue_token(
        username=user.username,
        tenant_id=user.tenant_id,
        roles=list(user.roles),
    )
    return LoginResponse(access_token=token)


@router.post("/register", summary="注册用户（需要管理员权限）")
async def register(
    req: RegisterRequest,
    auth: LimitedAdminAuth,
    db: AsyncSession = Depends(get_session),
) -> dict:
    existing = (
        await db.execute(select(User).where(User.username == req.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在")

    user = User(
        username=req.username,
        hashed_password=_hash_pwd(req.password),
        tenant_id=auth.tenant_id,  # 只能创建本租户用户
        roles=req.roles,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return {"ok": True, "user_id": user.id}


@router.post("/change-password", summary="修改密码（需要有效 JWT）")
async def change_password(
    req: ChangePasswordRequest,
    auth: QAAuth,
    db: AsyncSession = Depends(get_session),
) -> dict:
    user = (
        await db.execute(
            select(User).where(User.username == auth.user_id, User.is_active == True)  # noqa: E712
        )
    ).scalar_one_or_none()

    if user is None or not _verify_pwd(req.old_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="原密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user.hashed_password = _hash_pwd(req.new_password)
    await db.commit()
    return {"ok": True}

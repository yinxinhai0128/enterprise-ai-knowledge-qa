"""可信认证上下文：验证 Bearer JWT 并执行角色授权。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError

from app.config import settings

JWT_ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32
_INSECURE_SECRETS = {"", "replace_with_at_least_32_random_characters"}
_IDENTIFIER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


@dataclass(frozen=True, slots=True)
class AuthContext:
    """由已验签 claims 构造的服务端可信身份。"""

    user_id: str
    tenant_id: str
    roles: frozenset[str]


bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="由企业身份系统签发的 Bearer JWT",
    bearerFormat="JWT",
)


def _unauthorized(detail: str = "无效或已过期的访问令牌") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _validated_identifier(value: object, claim: str) -> str:
    """验证可安全拼入 thread ID 和过滤条件的身份字段。"""
    if not isinstance(value, str):
        raise _unauthorized(f"访问令牌缺少有效的 {claim}")
    normalized = value.strip()
    if not (1 <= len(normalized) <= settings.max_session_id_chars) or any(
        char not in _IDENTIFIER_CHARS for char in normalized
    ):
        raise _unauthorized(f"访问令牌中的 {claim} 格式无效")
    return normalized


async def get_auth_context(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
) -> AuthContext:
    """验签 JWT，并只从受验证 claims 生成身份。"""
    if credentials is None:
        raise _unauthorized("缺少 Bearer 访问令牌")
    if credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    secret = settings.auth_jwt_secret.get_secret_value()
    if len(secret) < MIN_SECRET_LENGTH or secret in _INSECURE_SECRETS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="身份认证服务尚未安全配置",
        )

    try:
        claims = jwt.decode(
            credentials.credentials,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=settings.auth_jwt_audience,
            issuer=settings.auth_jwt_issuer,
            options={"require": ["exp", "iat", "sub", "tenant_id", "roles"]},
        )
    except InvalidTokenError as exc:
        raise _unauthorized() from exc

    user_id = _validated_identifier(claims.get("sub"), "sub")
    tenant_id = _validated_identifier(claims.get("tenant_id"), "tenant_id")
    raw_roles = claims.get("roles")
    if not isinstance(raw_roles, list) or not (1 <= len(raw_roles) <= 16):
        raise _unauthorized("访问令牌缺少有效的 roles")
    roles = frozenset(_validated_identifier(role, "roles") for role in raw_roles)
    return AuthContext(user_id=user_id, tenant_id=tenant_id, roles=roles)


def require_role(role: str):
    """构造角色授权依赖；认证失败为 401，角色不足为 403。"""

    async def dependency(
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        if role not in auth.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return auth

    return dependency


require_user = require_role("user")
require_admin = require_role("admin")

UserAuth = Annotated[AuthContext, Depends(require_user)]
AdminAuth = Annotated[AuthContext, Depends(require_admin)]


def build_thread_id(auth: AuthContext, session_id: str) -> str:
    """用可信身份生成不可跨租户/跨用户碰撞的 Agent thread ID。"""
    normalized = session_id.strip()
    if not (1 <= len(normalized) <= 64) or any(
        char not in _IDENTIFIER_CHARS for char in normalized
    ):
        raise ValueError("invalid session_id")
    return f"{auth.tenant_id}:{auth.user_id}:{normalized}"

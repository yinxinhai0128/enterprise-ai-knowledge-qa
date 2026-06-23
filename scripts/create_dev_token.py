"""仅为本地 development 环境签发短期测试 JWT；生产环境拒绝运行。"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
_IDENTIFIER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)
_INSECURE_SECRETS = {"", "replace_with_at_least_32_random_characters"}


def _identifier(value: str, field: str) -> str:
    normalized = value.strip()
    if not (1 <= len(normalized) <= 64) or any(
        char not in _IDENTIFIER_CHARS for char in normalized
    ):
        raise ValueError(f"invalid {field}")
    return normalized


def create_dev_token(
    *,
    user_id: str,
    tenant_id: str,
    roles: list[str],
    ttl_seconds: int,
) -> str:
    if os.environ.get("APP_ENV", "development").lower() != "development":
        raise RuntimeError("dev token signing is disabled outside development")
    secret = os.environ.get("AUTH_JWT_SECRET", "")
    if len(secret) < 32 or secret in _INSECURE_SECRETS:
        raise RuntimeError("AUTH_JWT_SECRET is not safely configured")
    if not (1 <= ttl_seconds <= 3600):
        raise ValueError("ttl_seconds must be between 1 and 3600")
    if not roles or len(roles) > 16:
        raise ValueError("roles must contain between 1 and 16 entries")
    now = datetime.now(timezone.utc)
    claims = {
        "sub": _identifier(user_id, "user_id"),
        "tenant_id": _identifier(tenant_id, "tenant_id"),
        "roles": [_identifier(role, "role") for role in roles],
        "iss": os.environ.get("AUTH_JWT_ISSUER", "enterprise-idp"),
        "aud": os.environ.get("AUTH_JWT_AUDIENCE", "enterprise-kb"),
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--tenant-id", default="local-tenant")
    parser.add_argument("--roles", default="user", help="comma-separated roles")
    parser.add_argument("--ttl-seconds", type=int, default=900)
    args = parser.parse_args()
    try:
        token = create_dev_token(
            user_id=args.user_id,
            tenant_id=args.tenant_id,
            roles=[role.strip() for role in args.roles.split(",") if role.strip()],
            ttl_seconds=args.ttl_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

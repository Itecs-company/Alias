from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
settings = get_settings()


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire_delta = expires_delta or timedelta(minutes=settings.auth_access_token_expire_minutes)
    expire = datetime.now(timezone.utc) + expire_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def decode_access_token(token: str) -> Dict[str, Any]:
    return jwt.decode(token, settings.auth_secret_key, algorithms=[settings.auth_algorithm])


__all__ = [
    "create_access_token",
    "decode_access_token",
    "get_password_hash",
    "verify_password",
    "JWTError",
]

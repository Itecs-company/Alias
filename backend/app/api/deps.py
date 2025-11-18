from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import JWTError, decode_access_token
from app.models.user import User
from app.schemas.auth import AuthenticatedUser

auth_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncSession:
    async with get_session() as session:
        yield session


async def _resolve_user_from_token(token: str, session: AsyncSession) -> AuthenticatedUser:
    try:
        payload = decode_access_token(token)
    except JWTError as exc:  # pragma: no cover - runtime guard
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    username = payload.get("sub")
    role = payload.get("role")
    if not username or not role:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    if role != "admin":
        stmt = select(User).where(User.username == username)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return AuthenticatedUser(username=username, role=role)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    session: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    token = credentials.credentials
    return await _resolve_user_from_token(token, session)


async def get_user_from_header_or_query(
    token: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    session: AsyncSession = Depends(get_db),
) -> AuthenticatedUser:
    provided_token = credentials.credentials if credentials else token
    if not provided_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return await _resolve_user_from_token(provided_token, session)


async def require_admin(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")
    return user

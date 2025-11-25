from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class AuthenticatedUser(BaseModel):
    username: str
    role: str


class CredentialsUpdateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=4, max_length=255)


class CredentialsUpdateResponse(BaseModel):
    username: str
    message: str

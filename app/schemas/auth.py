from __future__ import annotations

from pydantic import Field

from app.schemas.common import Schema


class LoginRequest(Schema):
    email: str = Field(examples=["demo@advisor.test"])
    password: str = Field(examples=["demo1234"])


class UserOut(Schema):
    id: str
    email: str
    name: str
    role: str
    advisor_id: str
    firm: str


class TokenResponse(Schema):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

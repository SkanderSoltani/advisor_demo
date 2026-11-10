"""Mock authentication: bcrypt password hashing and HS256 JWTs. Demo only — not production auth."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    """Create a signed JWT for ``subject`` (the user id)."""
    s = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.JWT_EXPIRE_MINUTES)).timestamp()),
        **(extra or {}),
    }
    return jwt.encode(payload, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises ``jwt.PyJWTError`` on failure."""
    s = get_settings()
    return jwt.decode(token, s.JWT_SECRET, algorithms=[s.JWT_ALGORITHM])

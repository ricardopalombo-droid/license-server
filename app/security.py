from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)


def _normalize_password(password: str) -> str:
    if password is None:
        password = ""
    return unicodedata.normalize("NFKC", password)


def get_password_hash(password: str) -> str:
    password = _normalize_password(password)
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    password = _normalize_password(password)
    return pwd_context.verify(password, password_hash)


def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None
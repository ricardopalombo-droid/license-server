import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time

from app.config import settings


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_credit_access_token(license_id: int, ttl_minutes: int = 30) -> str:
    payload = {
        "license_id": int(license_id),
        "expires_at": int(time.time()) + ttl_minutes * 60,
        "nonce": secrets.token_urlsafe(12),
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_credit_access_token(token: str) -> int:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            settings.SECRET_KEY.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected_signature, _decode(supplied_signature)):
            raise ValueError("Assinatura inválida")
        payload = json.loads(_decode(encoded).decode("utf-8"))
        if int(payload["expires_at"]) < int(time.time()):
            raise ValueError("Acesso expirado")
        return int(payload["license_id"])
    except (binascii.Error, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Acesso de compra inválido ou expirado") from exc

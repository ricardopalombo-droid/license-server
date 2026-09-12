import base64
import json
from nacl.signing import SigningKey
from app.config import settings


def _get_signing_key() -> SigningKey:
    if not settings.LICENSE_SIGN_PRIVATE_KEY:
        raise RuntimeError("LICENSE_SIGN_PRIVATE_KEY não configurada no .env")
    raw = base64.b64decode(settings.LICENSE_SIGN_PRIVATE_KEY)
    return SigningKey(raw)


def get_public_key_base64() -> str:
    signing_key = _get_signing_key()
    return base64.b64encode(bytes(signing_key.verify_key)).decode("utf-8")


def serialize_payload(payload: dict) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":")
    ).encode("utf-8")


def sign_payload(payload: dict) -> str:
    signing_key = _get_signing_key()
    payload_bytes = serialize_payload(payload)
    signed = signing_key.sign(payload_bytes)
    signature = signed.signature
    return base64.b64encode(signature).decode("utf-8")

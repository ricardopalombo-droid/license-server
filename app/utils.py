import secrets
from datetime import datetime, timedelta


def generate_license_key() -> str:
    parts = [secrets.token_hex(2).upper() for _ in range(4)]
    return "-".join(parts)


def plan_expiration(plan_type: str) -> datetime:
    now = datetime.utcnow()
    if plan_type == "monthly":
        return now + timedelta(days=30)
    if plan_type == "annual":
        return now + timedelta(days=365)
    raise ValueError("Plano inválido")


def human_plan(plan_type: str) -> str:
    return "Mensal" if plan_type == "monthly" else "Anual"


def now_utc() -> datetime:
    return datetime.utcnow()

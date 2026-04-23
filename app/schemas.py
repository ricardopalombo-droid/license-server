from datetime import datetime
from pydantic import BaseModel, Field


class LoginForm(BaseModel):
    email: str
    password: str


class CustomerCreate(BaseModel):
    name: str
    company: str | None = None
    cpf_cnpj: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


class ProductCreate(BaseModel):
    name: str
    code: str


class LicenseCreate(BaseModel):
    customer_id: int
    product_id: int
    plan_type: str = Field(pattern="^(monthly|annual)$")
    max_concurrent_sessions: int = Field(ge=1, le=100)
    notes: str | None = None


class ActivateRequest(BaseModel):
    license_key: str
    machine_id: str
    machine_name: str | None = None


class HeartbeatRequest(BaseModel):
    session_token: str


class ReleaseRequest(BaseModel):
    session_token: str


class ActivateResponse(BaseModel):
    ok: bool
    session_token: str
    license_status: str
    expires_at: datetime
    offline_until: datetime
    heartbeat_seconds: int

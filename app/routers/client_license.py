from datetime import datetime, timedelta
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import License, LicenseSession
from app.schemas import ActivateRequest, HeartbeatRequest, ReleaseRequest

router = APIRouter(prefix="/client", tags=["client"])


def cleanup_expired_sessions(db: Session, timeout_minutes: int):
    limit = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    sessions = db.query(LicenseSession).filter(
        LicenseSession.status == "active",
        LicenseSession.last_heartbeat_at < limit
    ).all()

    changed = False
    for s in sessions:
        s.status = "timeout"
        s.ended_at = datetime.utcnow()
        changed = True

    if changed:
        db.commit()


@router.post("/activate")
def activate_license(data: ActivateRequest, request: Request, db: Session = Depends(get_db)):
    from app.config import settings

    cleanup_expired_sessions(db, settings.SESSION_TIMEOUT_MINUTES)

    lic = db.query(License).filter(License.license_key == data.license_key).first()
    if not lic:
        raise HTTPException(status_code=404, detail="Licença não encontrada")

    if lic.status == "blocked":
        raise HTTPException(status_code=403, detail="Licença bloqueada")

    if lic.status == "revoked":
        raise HTTPException(status_code=403, detail="Licença revogada")

    if lic.expires_at < datetime.utcnow():
        lic.status = "expired"
        db.commit()
        raise HTTPException(status_code=403, detail="Licença vencida")

    active_count = db.query(LicenseSession).filter(
        LicenseSession.license_id == lic.id,
        LicenseSession.status == "active",
    ).count()

    if active_count >= lic.max_concurrent_sessions:
        raise HTTPException(status_code=403, detail="Limite de sessões simultâneas atingido")

    session = LicenseSession(
        license_id=lic.id,
        machine_id=data.machine_id,
        machine_name=data.machine_name or "",
        ip_address=request.client.host if request.client else "",
        session_token=secrets.token_urlsafe(32),
        status="active",
        started_at=datetime.utcnow(),
        last_heartbeat_at=datetime.utcnow(),
    )
    db.add(session)

    lic.last_validation_at = datetime.utcnow()
    db.commit()
    db.refresh(session)

    offline_until = datetime.utcnow() + timedelta(days=lic.grace_days)

    from app.license_signing import sign_payload

    payload = {
        "session_token": session.session_token,
        "license_status": lic.status,
        "expires_at": lic.expires_at.isoformat(),
        "offline_until": offline_until.isoformat(),
        "heartbeat_seconds": 120,
        "license_key": lic.license_key,
        "machine_id": data.machine_id,
        "customer_name": lic.customer.company or lic.customer.name,
    }

    signature = sign_payload(payload)

    return {
        "ok": True,
        "payload": payload,
        "signature": signature,
    }


@router.post("/heartbeat")
def heartbeat(data: HeartbeatRequest, db: Session = Depends(get_db)):
    session = db.query(LicenseSession).filter(
        LicenseSession.session_token == data.session_token,
        LicenseSession.status == "active",
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    lic = db.query(License).filter(License.id == session.license_id).first()
    if not lic:
        raise HTTPException(status_code=404, detail="Licença não encontrada")

    if lic.status in ("blocked", "revoked", "expired"):
        raise HTTPException(status_code=403, detail="Licença indisponível")

    if lic.expires_at < datetime.utcnow():
        lic.status = "expired"
        db.commit()
        raise HTTPException(status_code=403, detail="Licença vencida")

    session.last_heartbeat_at = datetime.utcnow()
    lic.last_validation_at = datetime.utcnow()
    db.commit()

    return {"ok": True}


@router.post("/release")
def release(data: ReleaseRequest, db: Session = Depends(get_db)):
    session = db.query(LicenseSession).filter(
        LicenseSession.session_token == data.session_token,
        LicenseSession.status == "active",
    ).first()

    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    session.status = "closed"
    session.ended_at = datetime.utcnow()
    db.commit()

    return {"ok": True}
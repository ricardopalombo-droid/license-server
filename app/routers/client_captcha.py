from __future__ import annotations

import base64
import hashlib
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db
from app.models import CaptchaUsage, License, LicenseSession, Product
from app.schemas import CaptchaHcaptchaRequest, CaptchaImageRequest


router = APIRouter(prefix="/client/captcha", tags=["client-captcha"])

CAPMONSTER_API_BASE = "https://api.capmonster.cloud"
NONECAP_API_BASE = "https://api.nonecap.com/v1"
ALLOWED_NFE_HOSTS = {"www.nfe.fazenda.gov.br", "nfe.fazenda.gov.br"}
ALLOWED_NFE_PATH = "/portal/consultarecaptcha.aspx"
PROCESSING_STALE_MINUTES = 5
_limit_lock = threading.Lock()


def _safe_error_message(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "Erro desconhecido")).strip()
    return text[:500]


def _response_json(response: requests.Response, description: str) -> dict:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{description}: resposta inválida (HTTP {response.status_code}).") from exc
    if not response.ok:
        error = payload.get("error") or {}
        detail = (
            error.get("message")
            or payload.get("errorDescription")
            or payload.get("detail")
            or f"HTTP {response.status_code}"
        )
        raise RuntimeError(f"{description}: {detail}")
    return payload


def _active_captcha_session(db: Session, token: str) -> LicenseSession:
    session = (
        db.query(LicenseSession)
        .join(License)
        .join(Product)
        .filter(
            LicenseSession.session_token == token,
            LicenseSession.status == "active",
            License.status == "active",
            Product.code == settings.CAPTCHA_PRODUCT_CODE,
        )
        .first()
    )
    if not session:
        raise HTTPException(status_code=401, detail="Sessão de licença inválida para o Buscador XML.")

    now = datetime.utcnow()
    license_obj = session.license
    if license_obj.expires_at < now:
        license_obj.status = "expired"
        db.commit()
        raise HTTPException(status_code=403, detail="Licença vencida.")
    if session.last_heartbeat_at < now - timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES):
        session.status = "timeout"
        session.ended_at = now
        db.commit()
        raise HTTPException(status_code=401, detail="Sessão da licença expirou.")

    session.last_heartbeat_at = now
    license_obj.last_validation_at = now
    return session


def _reserve_usage(
    db: Session,
    session: LicenseSession,
    provider: str,
    captcha_type: str,
    request: Request,
    page_host: str | None = None,
    sitekey: str | None = None,
) -> CaptchaUsage:
    now = datetime.utcnow()
    hour_ago = now - timedelta(hours=1)
    stale_before = now - timedelta(minutes=PROCESSING_STALE_MINUTES)

    with _limit_lock:
        stale = db.query(CaptchaUsage).filter(
            CaptchaUsage.status == "processing",
            CaptchaUsage.created_at < stale_before,
        ).all()
        for item in stale:
            item.status = "timeout"
            item.completed_at = now
            item.error_code = "stale_request"
            item.error_message = "Solicitação interrompida antes da conclusão."

        hourly_count = db.query(CaptchaUsage).filter(
            CaptchaUsage.license_id == session.license_id,
            CaptchaUsage.created_at >= hour_ago,
        ).count()
        if hourly_count >= settings.CAPTCHA_RATE_LIMIT_PER_HOUR:
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Limite horário de captchas atingido para esta licença.",
            )

        license_concurrent = db.query(CaptchaUsage).filter(
            CaptchaUsage.license_id == session.license_id,
            CaptchaUsage.status == "processing",
            CaptchaUsage.created_at >= stale_before,
        ).count()
        if license_concurrent >= settings.CAPTCHA_MAX_CONCURRENT_PER_LICENSE:
            db.commit()
            raise HTTPException(
                status_code=429,
                detail="Limite de captchas simultâneos atingido para esta licença.",
            )

        global_concurrent = db.query(CaptchaUsage).filter(
            CaptchaUsage.status == "processing",
            CaptchaUsage.created_at >= stale_before,
        ).count()
        if global_concurrent >= settings.CAPTCHA_MAX_CONCURRENT_GLOBAL:
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="Capacidade simultânea de captchas temporariamente atingida.",
            )

        usage = CaptchaUsage(
            request_id=secrets.token_urlsafe(18),
            license_id=session.license_id,
            session_id=session.id,
            provider=provider,
            captcha_type=captcha_type,
            status="processing",
            page_host=page_host,
            sitekey_hash=hashlib.sha256(sitekey.encode("utf-8")).hexdigest() if sitekey else None,
            client_ip=request.client.host if request.client else None,
            created_at=now,
        )
        db.add(usage)
        db.commit()
        db.refresh(usage)
        return usage


def _complete_usage(
    db: Session,
    usage: CaptchaUsage,
    *,
    status: str,
    started: float,
    task_id: object = None,
    provider_cost: object = None,
    error_code: str | None = None,
    error_message: object = None,
) -> None:
    usage.status = status
    usage.completed_at = datetime.utcnow()
    usage.duration_ms = max(0, int((time.monotonic() - started) * 1000))
    usage.provider_task_id = str(task_id)[:120] if task_id is not None else None
    usage.provider_cost = str(provider_cost)[:50] if provider_cost is not None else None
    usage.error_code = error_code[:80] if error_code else None
    usage.error_message = _safe_error_message(error_message) if error_message else None
    db.commit()


def _validate_sefaz_image(image_base64: str) -> bytes:
    encoded = image_base64.strip()
    if encoded.startswith("data:"):
        try:
            header, encoded = encoded.split(",", 1)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Imagem de captcha inválida.") from exc
        if "base64" not in header.lower():
            raise HTTPException(status_code=400, detail="A imagem deve estar em base64.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Imagem de captcha inválida.") from exc
    if not 32 <= len(raw) <= 1_000_000:
        raise HTTPException(status_code=400, detail="Tamanho da imagem de captcha inválido.")
    if not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
        raise HTTPException(status_code=400, detail="Somente capturas PNG ou JPEG são aceitas.")
    return raw


def _validate_nfe_page(page_url: str, sitekey: str) -> str:
    parsed = urlparse(page_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or host not in ALLOWED_NFE_HOSTS:
        raise HTTPException(status_code=400, detail="Somente o Portal Nacional da NF-e é permitido.")
    if parsed.path.lower() != ALLOWED_NFE_PATH:
        raise HTTPException(status_code=400, detail="Página não autorizada para resolução de captcha.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", sitekey):
        raise HTTPException(status_code=400, detail="Identificador do hCaptcha inválido.")
    return host


def solve_capmonster_image(image_base64: str) -> dict:
    if not settings.CAPMONSTER_API_KEY:
        raise RuntimeError("CapMonster não está configurado no servidor.")
    create_response = requests.post(
        f"{CAPMONSTER_API_BASE}/createTask",
        json={
            "clientKey": settings.CAPMONSTER_API_KEY,
            "task": {"type": "ImageToTextTask", "body": image_base64},
        },
        timeout=45,
    )
    created = _response_json(create_response, "Falha ao criar tarefa no CapMonster")
    if created.get("errorId") not in (None, 0):
        raise RuntimeError(created.get("errorDescription") or created.get("errorCode") or "Erro CapMonster")
    task_id = created.get("taskId")
    if not task_id:
        raise RuntimeError("CapMonster não devolveu o identificador da tarefa.")

    deadline = time.monotonic() + settings.CAPTCHA_REQUEST_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(1.5)
        result_response = requests.post(
            f"{CAPMONSTER_API_BASE}/getTaskResult",
            json={"clientKey": settings.CAPMONSTER_API_KEY, "taskId": task_id},
            timeout=45,
        )
        result = _response_json(result_response, "Falha ao consultar tarefa no CapMonster")
        if result.get("errorId") not in (None, 0):
            raise RuntimeError(result.get("errorDescription") or result.get("errorCode") or "Erro CapMonster")
        if result.get("status") == "processing":
            continue
        if result.get("status") != "ready":
            raise RuntimeError(f"Status inesperado do CapMonster: {result.get('status')}")
        text = str((result.get("solution") or {}).get("text") or "").strip()
        if not text:
            raise RuntimeError("CapMonster não devolveu o texto do captcha.")
        return {"text": text, "task_id": task_id, "cost": result.get("cost")}
    raise TimeoutError("CapMonster não resolveu o captcha dentro do prazo.")


def solve_nonecap_hcaptcha(page_url: str, sitekey: str, user_agent: str, rqdata: str | None) -> dict:
    if not settings.NONECAP_API_KEY:
        raise RuntimeError("NoneCap não está configurado no servidor.")
    headers = {
        "Authorization": f"Bearer {settings.NONECAP_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "type": "hcaptcha_enterprise" if rqdata else "hcaptcha",
        "sitekey": sitekey,
        "url": page_url,
        "user_agent": user_agent,
    }
    if rqdata:
        payload["rqdata"] = rqdata
    response = requests.post(
        f"{NONECAP_API_BASE}/solves",
        headers=headers,
        params={"wait": 30},
        json=payload,
        timeout=45,
    )
    solve = _response_json(response, "Falha ao criar resolução na NoneCap")
    solve_id = solve.get("id")
    if not solve_id:
        raise RuntimeError("NoneCap não devolveu o identificador da resolução.")

    deadline = time.monotonic() + settings.CAPTCHA_REQUEST_TIMEOUT_SECONDS
    terminal = {"solved", "failed", "cancelled", "expired"}
    while solve.get("status") not in terminal and time.monotonic() < deadline:
        poll = requests.get(
            f"{NONECAP_API_BASE}/solves/{solve_id}",
            headers=headers,
            params={"wait": 10},
            timeout=45,
        )
        solve = _response_json(poll, "Falha ao consultar resolução na NoneCap")
    if solve.get("status") != "solved" or not solve.get("token"):
        error = solve.get("error") or {}
        raise RuntimeError(error.get("message") or f"NoneCap não resolveu o captcha: {solve.get('status')}")
    return {
        "token": solve["token"],
        "response_key": solve.get("resp_key"),
        "task_id": solve_id,
        "cost": solve.get("cost") or solve.get("credits_used"),
    }


@router.post("/sp-image")
def solve_sp_image(
    data: CaptchaImageRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    _validate_sefaz_image(data.image_base64)
    session = _active_captcha_session(db, data.session_token)
    usage = _reserve_usage(db, session, "capmonster", "sefaz_sp_image", request, page_host="nfe.fazenda.sp.gov.br")
    started = time.monotonic()
    try:
        solved = solve_capmonster_image(data.image_base64)
        _complete_usage(
            db,
            usage,
            status="solved",
            started=started,
            task_id=solved.get("task_id"),
            provider_cost=solved.get("cost"),
        )
        return {"ok": True, "request_id": usage.request_id, "text": solved["text"]}
    except Exception as exc:
        code = "timeout" if isinstance(exc, TimeoutError) else "provider_error"
        _complete_usage(db, usage, status="failed", started=started, error_code=code, error_message=exc)
        raise HTTPException(status_code=502, detail=_safe_error_message(exc)) from exc


@router.post("/nfe-hcaptcha")
def solve_nfe_hcaptcha(
    data: CaptchaHcaptchaRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    host = _validate_nfe_page(data.page_url, data.sitekey)
    session = _active_captcha_session(db, data.session_token)
    usage = _reserve_usage(
        db,
        session,
        "nonecap",
        "portal_nacional_hcaptcha",
        request,
        page_host=host,
        sitekey=data.sitekey,
    )
    started = time.monotonic()
    try:
        solved = solve_nonecap_hcaptcha(
            data.page_url,
            data.sitekey,
            data.user_agent,
            data.rqdata,
        )
        _complete_usage(
            db,
            usage,
            status="solved",
            started=started,
            task_id=solved.get("task_id"),
            provider_cost=solved.get("cost"),
        )
        return {
            "ok": True,
            "request_id": usage.request_id,
            "token": solved["token"],
            "response_key": solved.get("response_key"),
        }
    except Exception as exc:
        code = "timeout" if isinstance(exc, TimeoutError) else "provider_error"
        _complete_usage(db, usage, status="failed", started=started, error_code=code, error_message=exc)
        raise HTTPException(status_code=502, detail=_safe_error_message(exc)) from exc

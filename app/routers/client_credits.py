from datetime import datetime, timedelta
import hashlib
import hmac
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.dependencies import get_db
from app.models import (
    CreditEntitlement,
    CreditLedger,
    CreditQuote,
    CreditQuoteItem,
    License,
    LicenseCreditAccount,
    LicenseSession,
)
from app.schemas import CreditQuoteOperation, CreditQuoteRequest, CreditReservationOperation


router = APIRouter(prefix="/client/credits", tags=["client-credits"])
QUOTE_MINUTES = 15


def active_session(db: Session, token: str) -> LicenseSession:
    session = db.query(LicenseSession).filter(
        LicenseSession.session_token == token,
        LicenseSession.status == "active",
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    license_obj = db.query(License).filter(License.id == session.license_id).first()
    if not license_obj or license_obj.status != "active" or license_obj.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Licença indisponível")
    session.last_heartbeat_at = datetime.utcnow()
    return session


def credit_account(db: Session, license_id: int) -> LicenseCreditAccount:
    account = db.query(LicenseCreditAccount).filter(
        LicenseCreditAccount.license_id == license_id
    ).first()
    if not account or not account.enabled:
        raise HTTPException(status_code=403, detail="Cobrança por créditos não está habilitada nesta licença")
    return account


def company_hash(company_key: str) -> str:
    canonical = re.sub(r"\D", "", company_key)
    if len(canonical) < 8:
        raise HTTPException(status_code=422, detail="Identificador da empresa inválido")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def ledger(db: Session, account: LicenseCreditAccount, delta: int, event_type: str, reference: str, notes=""):
    db.add(CreditLedger(
        account_id=account.id,
        delta=delta,
        balance_after=account.balance,
        event_type=event_type,
        reference=reference,
        notes=notes or None,
    ))


def cleanup_expired_quotes(db: Session, license_id: int):
    now = datetime.utcnow()
    expired = db.query(CreditQuote).filter(
        CreditQuote.license_id == license_id,
        CreditQuote.status.in_(("quoted", "reserved")),
        CreditQuote.expires_at < now,
    ).all()
    for quote in expired:
        if quote.status == "reserved" and quote.required_credits:
            account = db.query(LicenseCreditAccount).filter(
                LicenseCreditAccount.license_id == quote.license_id
            ).first()
            if account:
                account.balance += quote.required_credits
                ledger(db, account, quote.required_credits, "reservation_expired", quote.reservation_id or quote.quote_id)
        quote.status = "expired"
    if expired:
        db.commit()


def quote_response(quote: CreditQuote, account: LicenseCreditAccount):
    return {
        "billing_enabled": True,
        "quote_id": quote.quote_id,
        "total_items": quote.total_items,
        "unlocked_items": quote.unlocked_items,
        "required_credits": quote.required_credits,
        "credit_balance": account.balance,
        "balance_after": account.balance - quote.required_credits,
        "unit_price_cents": quote.unit_price_cents,
        "amount_cents": quote.required_credits * quote.unit_price_cents,
        "can_run": account.balance >= quote.required_credits,
        "expires_at": quote.expires_at.isoformat(),
    }


@router.post("/quote")
def create_quote(data: CreditQuoteRequest, db: Session = Depends(get_db)):
    session = active_session(db, data.session_token)
    account = credit_account(db, session.license_id)
    cleanup_expired_quotes(db, session.license_id)

    unique = {}
    for item in data.items:
        hashed = company_hash(item.company_key)
        unique[(hashed, item.competence)] = (item, hashed)

    entitlements = db.query(CreditEntitlement).filter(
        CreditEntitlement.license_id == session.license_id
    ).all()
    unlocked = {(item.company_hash, item.competence) for item in entitlements}
    required = sum(1 for key in unique if key not in unlocked)
    now = datetime.utcnow()
    quote = CreditQuote(
        quote_id=secrets.token_urlsafe(32),
        license_id=session.license_id,
        session_id=session.id,
        status="quoted",
        total_items=len(unique),
        unlocked_items=len(unique) - required,
        required_credits=required,
        unit_price_cents=account.unit_price_cents,
        balance_before=account.balance,
        created_at=now,
        expires_at=now + timedelta(minutes=QUOTE_MINUTES),
    )
    db.add(quote)
    db.flush()
    for key, (item, hashed) in unique.items():
        db.add(CreditQuoteItem(
            quote_id=quote.id,
            company_hash=hashed,
            competence=item.competence,
            company_alias=item.company_alias,
            company_name=item.company_name,
            is_new=key not in unlocked,
        ))
    db.commit()
    db.refresh(quote)
    return quote_response(quote, account)


@router.post("/reserve")
def reserve(data: CreditQuoteOperation, db: Session = Depends(get_db)):
    session = active_session(db, data.session_token)
    cleanup_expired_quotes(db, session.license_id)
    quote = db.query(CreditQuote).filter(
        CreditQuote.quote_id == data.quote_id,
        CreditQuote.license_id == session.license_id,
        CreditQuote.session_id == session.id,
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Prévia de créditos não encontrada")
    now = datetime.utcnow()
    if quote.status != "quoted" or quote.expires_at < now:
        raise HTTPException(status_code=409, detail="A prévia expirou ou já foi utilizada")
    account = credit_account(db, session.license_id)
    reservation_id = secrets.token_urlsafe(32)
    reserved = db.query(CreditQuote).filter(
        CreditQuote.id == quote.id,
        CreditQuote.status == "quoted",
        CreditQuote.expires_at >= now,
    ).update({
        CreditQuote.status: "reserved",
        CreditQuote.reservation_id: reservation_id,
        CreditQuote.reserved_at: now,
        CreditQuote.expires_at: now + timedelta(minutes=QUOTE_MINUTES),
    }, synchronize_session=False)
    if not reserved:
        db.rollback()
        raise HTTPException(status_code=409, detail="A prévia expirou ou já foi utilizada")
    debited = db.query(LicenseCreditAccount).filter(
        LicenseCreditAccount.id == account.id,
        LicenseCreditAccount.balance >= quote.required_credits,
    ).update({
        LicenseCreditAccount.balance: LicenseCreditAccount.balance - quote.required_credits,
    }, synchronize_session=False)
    if not debited:
        db.rollback()
        raise HTTPException(status_code=402, detail="Saldo de créditos insuficiente")
    db.refresh(account)
    if quote.required_credits:
        ledger(db, account, -quote.required_credits, "reservation", reservation_id)
    db.commit()
    return {
        "ok": True,
        "reservation_id": reservation_id,
        "reserved_credits": quote.required_credits,
        "credit_balance": account.balance,
    }


@router.post("/commit")
def commit(data: CreditReservationOperation, db: Session = Depends(get_db)):
    session = active_session(db, data.session_token)
    quote = db.query(CreditQuote).filter(
        CreditQuote.reservation_id == data.reservation_id,
        CreditQuote.license_id == session.license_id,
        CreditQuote.session_id == session.id,
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Reserva de créditos não encontrada")
    account = credit_account(db, session.license_id)
    if quote.status == "committed":
        return {"ok": True, "credit_balance": account.balance, "consumed_credits": quote.required_credits}
    if quote.status != "reserved" or quote.expires_at < datetime.utcnow():
        raise HTTPException(status_code=409, detail="A reserva expirou ou não está disponível")
    for item in quote.items:
        if not item.is_new:
            continue
        exists = db.query(CreditEntitlement).filter(
            CreditEntitlement.license_id == session.license_id,
            CreditEntitlement.company_hash == item.company_hash,
            CreditEntitlement.competence == item.competence,
        ).first()
        if not exists:
            db.add(CreditEntitlement(
                license_id=session.license_id,
                company_hash=item.company_hash,
                competence=item.competence,
                company_alias=item.company_alias,
                company_name=item.company_name,
            ))
    quote.status = "committed"
    quote.committed_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "credit_balance": account.balance, "consumed_credits": quote.required_credits}


@router.post("/cancel")
def cancel(data: CreditReservationOperation, db: Session = Depends(get_db)):
    session = active_session(db, data.session_token)
    quote = db.query(CreditQuote).filter(
        CreditQuote.reservation_id == data.reservation_id,
        CreditQuote.license_id == session.license_id,
        CreditQuote.session_id == session.id,
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Reserva de créditos não encontrada")
    account = credit_account(db, session.license_id)
    if quote.status == "cancelled":
        return {"ok": True, "credit_balance": account.balance}
    if quote.status != "reserved":
        raise HTTPException(status_code=409, detail="A reserva não pode mais ser cancelada")
    account.balance += quote.required_credits
    quote.status = "cancelled"
    if quote.required_credits:
        ledger(db, account, quote.required_credits, "reservation_cancelled", quote.reservation_id)
    db.commit()
    return {"ok": True, "credit_balance": account.balance}

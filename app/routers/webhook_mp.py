from datetime import datetime, timedelta
import smtplib
from email.message import EmailMessage

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Customer, Product, License
from app.utils import generate_license_key
from app.config import settings

router = APIRouter(prefix="/webhook", tags=["webhook"])


def enviar_email_licenca(destinatario: str, nome_produto: str, license_key: str, expires_at: datetime):
    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    smtp_user = settings.SMTP_USER
    smtp_password = settings.SMTP_PASSWORD
    smtp_from = settings.SMTP_FROM or smtp_user

    if not smtp_host or not smtp_user or not smtp_password or not smtp_from:
        print("⚠️ SMTP não configurado. E-mail não enviado.")
        return

    assunto = f"Sua licença foi criada - {nome_produto}"
    corpo = f"""
Olá,

Sua licença foi criada com sucesso.

Produto: {nome_produto}
Chave da licença: {license_key}
Válida até: {expires_at.strftime("%d/%m/%Y %H:%M")}

Guarde esta chave com segurança. Ela será usada no seu sistema para ativação.

Atenciosamente,
PalSys
""".strip()

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = smtp_from
    msg["To"] = destinatario
    msg.set_content(corpo)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)

    print(f"📧 E-mail enviado para {destinatario}")


def buscar_ou_criar_cliente(db: Session, email: str, nome: str) -> Customer:
    cliente = db.query(Customer).filter(Customer.email == email).first()

    if cliente:
        if nome and cliente.name != nome:
            cliente.name = nome
            db.commit()
            db.refresh(cliente)
        return cliente

    cliente = Customer(
        name=nome or email,
        email=email,
    )
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


def buscar_produto(db: Session, produto_code: str) -> Product | None:
    return db.query(Product).filter(Product.code == produto_code).first()


def buscar_licenca_por_subscription(db: Session, subscription_id: str) -> License | None:
    return db.query(License).filter(License.mp_subscription_id == subscription_id).first()


def buscar_licenca_por_cliente_produto(
    db: Session, customer_id: int, product_id: int
) -> License | None:
    return (
        db.query(License)
        .filter(
            License.customer_id == customer_id,
            License.product_id == product_id,
        )
        .order_by(License.id.desc())
        .first()
    )


def renovar_mais_30_dias(data_base: datetime | None) -> datetime:
    agora = datetime.utcnow()
    base = data_base if data_base and data_base > agora else agora
    return base + timedelta(days=30)


@router.post("/mercadopago")
def webhook_mercadopago(
    data: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    token_esperado = settings.LICENSE_API_TOKEN.strip()

    if not token_esperado:
        raise HTTPException(status_code=500, detail="LICENSE_API_TOKEN não configurado")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente")

    token_recebido = authorization.replace("Bearer ", "", 1).strip()
    if token_recebido != token_esperado:
        raise HTTPException(status_code=403, detail="Token inválido")

    print("🔥 RECEBIDO DO SITE:", data)

    email = (data.get("email") or "").strip().lower()
    nome = (data.get("nome") or "").strip()
    produto_code = str(data.get("produto") or "").strip()
    status = str(data.get("status") or "").strip().lower()
    assinatura_id = str(data.get("assinatura_id") or "").strip()
    pagamento_id = str(data.get("pagamento_id") or "").strip()

    if not email or not produto_code:
        return {"ok": False, "erro": "dados inválidos"}

    if not assinatura_id:
        return {"ok": False, "erro": "assinatura_id obrigatório"}

    cliente = buscar_ou_criar_cliente(db, email, nome)

    produto = buscar_produto(db, produto_code)
    if not produto:
        return {"ok": False, "erro": "produto não encontrado"}

    lic = buscar_licenca_por_subscription(db, assinatura_id)

    if not lic:
        lic = buscar_licenca_por_cliente_produto(db, cliente.id, produto.id)
        if lic and not lic.mp_subscription_id:
            lic.mp_subscription_id = assinatura_id
            db.commit()
            db.refresh(lic)

    if status == "authorized":
        if not lic:
            lic = License(
                customer_id=cliente.id,
                product_id=produto.id,
                license_key=generate_license_key(),
                plan_type="monthly",
                status="active",
                max_concurrent_sessions=1,
                grace_days=4,
                expires_at=datetime.utcnow() + timedelta(days=30),
                mp_subscription_id=assinatura_id,
                mp_last_payment_id=pagamento_id or None,
            )
            db.add(lic)
            db.commit()
            db.refresh(lic)

            print("✅ LICENÇA CRIADA:", lic.license_key)

            try:
                enviar_email_licenca(
                    destinatario=cliente.email,
                    nome_produto=produto.name,
                    license_key=lic.license_key,
                    expires_at=lic.expires_at,
                )
            except Exception as e:
                print("⚠️ Erro ao enviar e-mail:", e)

            return {
                "ok": True,
                "acao": "licenca_criada",
                "license_id": lic.id,
                "license_key": lic.license_key,
            }

        lic.status = "active"
        lic.mp_subscription_id = assinatura_id
        if pagamento_id:
            lic.mp_last_payment_id = pagamento_id
        db.commit()

        print("ℹ️ LICENÇA JÁ EXISTIA, SOMENTE REATIVADA/VINCULADA")
        return {
            "ok": True,
            "acao": "licenca_reativada",
            "license_id": lic.id,
            "license_key": lic.license_key,
        }

    if status == "approved":
        if not lic:
            lic = License(
                customer_id=cliente.id,
                product_id=produto.id,
                license_key=generate_license_key(),
                plan_type="monthly",
                status="active",
                max_concurrent_sessions=1,
                grace_days=4,
                expires_at=datetime.utcnow() + timedelta(days=30),
                mp_subscription_id=assinatura_id,
                mp_last_payment_id=pagamento_id or None,
            )
            db.add(lic)
            db.commit()
            db.refresh(lic)

            print("✅ LICENÇA CRIADA A PARTIR DO PAGAMENTO:", lic.license_key)

            try:
                enviar_email_licenca(
                    destinatario=cliente.email,
                    nome_produto=produto.name,
                    license_key=lic.license_key,
                    expires_at=lic.expires_at,
                )
            except Exception as e:
                print("⚠️ Erro ao enviar e-mail:", e)

            return {
                "ok": True,
                "acao": "licenca_criada_via_pagamento",
                "license_id": lic.id,
                "license_key": lic.license_key,
            }

        if pagamento_id and lic.mp_last_payment_id == pagamento_id:
            print("ℹ️ PAGAMENTO JÁ PROCESSADO, IGNORANDO DUPLICIDADE")
            return {
                "ok": True,
                "acao": "pagamento_duplicado_ignorado",
                "license_id": lic.id,
                "license_key": lic.license_key,
            }

        lic.expires_at = renovar_mais_30_dias(lic.expires_at)
        lic.status = "active"
        lic.plan_type = "monthly"
        lic.mp_subscription_id = assinatura_id
        if pagamento_id:
            lic.mp_last_payment_id = pagamento_id

        db.commit()
        db.refresh(lic)

        print("🔄 LICENÇA RENOVADA:", lic.license_key)
        return {
            "ok": True,
            "acao": "licenca_renovada",
            "license_id": lic.id,
            "license_key": lic.license_key,
            "expires_at": lic.expires_at.isoformat(),
        }

    if status in ["cancelled", "paused", "blocked"]:
        if lic:
            lic.status = "blocked"
            lic.mp_subscription_id = assinatura_id
            if pagamento_id:
                lic.mp_last_payment_id = pagamento_id
            db.commit()

            print("⛔ LICENÇA BLOQUEADA")
            return {
                "ok": True,
                "acao": "licenca_bloqueada",
                "license_id": lic.id,
                "license_key": lic.license_key,
            }

        return {"ok": True, "acao": "nada_para_bloquear"}

    return {"ok": True, "acao": "sem_acao", "status": status}
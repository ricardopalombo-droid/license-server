from datetime import datetime, timedelta
import smtplib
import secrets
from email.message import EmailMessage

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Customer, Product, License, LicenseCreditAccount, CreditLedger, CreditPurchase
from app.utils import generate_license_key
from app.config import settings
from app.credit_access import verify_credit_access_token

router = APIRouter(prefix="/webhook", tags=["webhook"])


def validar_token_integracao(authorization: str | None):
    token_esperado = settings.LICENSE_API_TOKEN.strip()
    if not token_esperado:
        raise HTTPException(status_code=500, detail="LICENSE_API_TOKEN não configurado")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente")
    if authorization.replace("Bearer ", "", 1).strip() != token_esperado:
        raise HTTPException(status_code=403, detail="Token inválido")


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


def enviar_email_creditos(destinatario: str, license_key: str, quantity: int, balance: int):
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        return
    msg = EmailMessage()
    msg["Subject"] = "Créditos liberados - PalSys Auditor Integrado"
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = destinatario
    msg.set_content(
        "Sua compra foi aprovada.\n\n"
        f"Créditos adicionados: {quantity}\n"
        f"Saldo atual: {balance}\n"
        f"Chave da licença: {license_key}\n\n"
        "Baixar o PalSys Auditor Integrado:\n"
        "https://www.palsys.com.br/api/download/auditor-integrado\n\n"
        "Cada crédito libera uma empresa em uma competência. "
        "Competências já liberadas podem ser reprocessadas sem novo consumo."
    )
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


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


def license_from_credit_access(db: Session, access_token: str, product_code: str = "22") -> License:
    try:
        license_id = verify_credit_access_token(access_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    license_obj = db.query(License).join(Product).filter(
        License.id == license_id,
        Product.code == product_code,
        License.status == "active",
    ).first()
    if not license_obj:
        raise HTTPException(status_code=404, detail="Licença do Auditor Integrado não encontrada")
    return license_obj


@router.post("/credits/customer-context")
def credit_customer_context(
    data: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    validar_token_integracao(authorization)
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=422, detail="Acesso de compra não informado")
    license_obj = license_from_credit_access(db, access_token)
    account = license_obj.credit_account
    if not license_obj.customer.email:
        raise HTTPException(status_code=422, detail="O cadastro da licença não possui e-mail")
    return {
        "ok": True,
        "customer_name": license_obj.customer.name,
        "customer_email": license_obj.customer.email,
        "license_hint": f"•••• {license_obj.license_key[-6:]}",
        "credit_balance": account.balance if account else 0,
        "unit_price_cents": account.unit_price_cents if account else settings.AUDITOR_CREDIT_PRICE_CENTS,
    }


@router.post("/credits/price")
def credit_price(
    data: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    validar_token_integracao(authorization)
    license_key = str(data.get("license_key") or "").strip().upper()
    access_token = str(data.get("access_token") or "").strip()
    product_code = str(data.get("product_code") or "22").strip().upper()
    unit_price = settings.AUDITOR_CREDIT_PRICE_CENTS
    if access_token:
        license_obj = license_from_credit_access(db, access_token, product_code)
        if license_obj.credit_account:
            unit_price = license_obj.credit_account.unit_price_cents
    elif license_key:
        license_obj = db.query(License).join(Product).filter(
            License.license_key == license_key,
            Product.code == product_code,
        ).first()
        if not license_obj:
            raise HTTPException(status_code=404, detail="Licença não encontrada para o Auditor Integrado")
        if license_obj.credit_account:
            unit_price = license_obj.credit_account.unit_price_cents
    return {"unit_price_cents": unit_price}


@router.post("/credits/preview")
def preview_credit_purchase(
    data: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    validar_token_integracao(authorization)
    email = str(data.get("email") or "").strip().lower()
    name = str(data.get("name") or "").strip()
    license_key = str(data.get("license_key") or "").strip().upper()
    access_token = str(data.get("access_token") or "").strip()
    product_code = str(data.get("product_code") or "22").strip().upper()
    try:
        quantity = int(data.get("quantity") or 0)
    except (TypeError, ValueError):
        quantity = 0
    if quantity < 1 or quantity > 10000:
        raise HTTPException(status_code=422, detail="Quantidade de créditos inválida")
    product = db.query(Product).filter(Product.code == product_code, Product.is_active == True).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto de créditos não encontrado")
    license_obj = None
    if access_token:
        license_obj = license_from_credit_access(db, access_token, product_code)
        email = str(license_obj.customer.email or "").strip().lower()
        name = str(license_obj.customer.name or "").strip()
        if not email:
            raise HTTPException(status_code=422, detail="O cadastro da licença não possui e-mail")
    elif license_key:
        license_obj = db.query(License).filter(
            License.license_key == license_key,
            License.product_id == product.id,
        ).first()
        if not license_obj:
            raise HTTPException(status_code=404, detail="A licença informada não pertence ao Auditor Integrado")
    else:
        if not email:
            raise HTTPException(status_code=422, detail="E-mail não informado")
        customer = db.query(Customer).filter(Customer.email == email).first()
        if customer:
            license_obj = db.query(License).filter(
                License.customer_id == customer.id,
                License.product_id == product.id,
            ).order_by(License.id.desc()).first()
    unit_price = (
        license_obj.credit_account.unit_price_cents
        if license_obj and license_obj.credit_account
        else settings.AUDITOR_CREDIT_PRICE_CENTS
    )
    purchase = CreditPurchase(
        order_id=secrets.token_urlsafe(24),
        license_id=license_obj.id if license_obj else None,
        product_id=product.id,
        customer_email=email,
        customer_name=name or None,
        quantity=quantity,
        unit_price_cents=unit_price,
        amount_cents=quantity * unit_price,
        status="pending",
    )
    db.add(purchase)
    db.commit()
    return {
        "ok": True,
        "order_id": purchase.order_id,
        "quantity": purchase.quantity,
        "unit_price_cents": purchase.unit_price_cents,
        "amount_cents": purchase.amount_cents,
        "product_name": product.name,
        "customer_name": name,
        "customer_email": email,
    }


@router.post("/credits/confirm")
def confirm_credit_purchase(
    data: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    validar_token_integracao(authorization)
    order_id = str(data.get("order_id") or "").strip()
    payment_id = str(data.get("payment_id") or "").strip()
    status = str(data.get("status") or "").strip().lower()
    try:
        amount_cents = int(data.get("amount_cents") or 0)
    except (TypeError, ValueError):
        amount_cents = 0
    if status != "approved" or not order_id or not payment_id:
        raise HTTPException(status_code=422, detail="Pagamento de créditos ainda não aprovado")
    purchase = db.query(CreditPurchase).filter(CreditPurchase.order_id == order_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Pedido de créditos não encontrado")
    if amount_cents != purchase.amount_cents:
        raise HTTPException(status_code=409, detail="O valor pago não corresponde ao pedido de créditos")
    if purchase.status == "approved":
        license_obj = db.query(License).filter(License.id == purchase.license_id).first()
        return {
            "ok": True,
            "action": "duplicate_ignored",
            "license_key": license_obj.license_key if license_obj else None,
            "credit_balance": license_obj.credit_account.balance if license_obj and license_obj.credit_account else 0,
        }
    duplicate = db.query(CreditPurchase).filter(CreditPurchase.payment_id == payment_id).first()
    if duplicate and duplicate.id != purchase.id:
        raise HTTPException(status_code=409, detail="Pagamento já utilizado em outro pedido")
    license_obj = db.query(License).filter(License.id == purchase.license_id).first() if purchase.license_id else None
    if not license_obj:
        customer = buscar_ou_criar_cliente(db, purchase.customer_email, purchase.customer_name or purchase.customer_email)
        license_obj = db.query(License).filter(
            License.customer_id == customer.id,
            License.product_id == purchase.product_id,
        ).order_by(License.id.desc()).first()
        if not license_obj:
            license_obj = License(
                customer_id=customer.id,
                product_id=purchase.product_id,
                license_key=generate_license_key(),
                plan_type="credits",
                status="active",
                max_concurrent_sessions=1,
                grace_days=0,
                expires_at=datetime(2099, 12, 31, 23, 59, 59),
            )
            db.add(license_obj)
            db.flush()
    license_obj.plan_type = "credits"
    license_obj.status = "active"
    license_obj.expires_at = datetime(2099, 12, 31, 23, 59, 59)
    account = license_obj.credit_account
    if not account:
        account = LicenseCreditAccount(
            license_id=license_obj.id,
            enabled=True,
            balance=0,
            unit_price_cents=purchase.unit_price_cents,
        )
        db.add(account)
        db.flush()
    account.enabled = True
    account.balance += purchase.quantity
    db.add(CreditLedger(
        account_id=account.id,
        delta=purchase.quantity,
        balance_after=account.balance,
        event_type="purchase",
        reference=f"payment:{payment_id}",
        notes=f"Compra aprovada: {purchase.quantity} crédito(s).",
    ))
    purchase.license_id = license_obj.id
    purchase.payment_id = payment_id
    purchase.status = "approved"
    purchase.paid_at = datetime.utcnow()
    db.commit()
    try:
        enviar_email_creditos(
            purchase.customer_email, license_obj.license_key, purchase.quantity, account.balance
        )
    except Exception as exc:
        print("Erro ao enviar e-mail dos creditos:", exc)
    return {
        "ok": True,
        "action": "credits_added",
        "license_key": license_obj.license_key,
        "credits_added": purchase.quantity,
        "credit_balance": account.balance,
    }


@router.post("/mercadopago")
def webhook_mercadopago(
    data: dict,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    validar_token_integracao(authorization)

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

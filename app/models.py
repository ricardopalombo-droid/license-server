from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database import Base


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    company = Column(String(150), nullable=True)
    cpf_cnpj = Column(String(30), nullable=True)
    email = Column(String(150), nullable=True)
    phone = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    licenses = relationship("License", back_populates="customer")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    code = Column(String(80), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)

    licenses = relationship("License", back_populates="product")


class License(Base):
    __tablename__ = "licenses"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    license_key = Column(String(100), unique=True, nullable=False, index=True)
    plan_type = Column(String(20), nullable=False)
    status = Column(String(20), default="active")

    max_concurrent_sessions = Column(Integer, default=1)
    grace_days = Column(Integer, default=4)

    issued_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_validation_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)

    # NOVOS CAMPOS
    mp_subscription_id = Column(String(100), unique=True, nullable=True, index=True)
    mp_last_payment_id = Column(String(100), nullable=True)

    customer = relationship("Customer", back_populates="licenses")
    product = relationship("Product", back_populates="licenses")
    sessions = relationship("LicenseSession", back_populates="license")
    credit_account = relationship(
        "LicenseCreditAccount", back_populates="license", uselist=False,
        cascade="all, delete-orphan",
    )


class LicenseSession(Base):
    __tablename__ = "license_sessions"

    id = Column(Integer, primary_key=True, index=True)
    license_id = Column(Integer, ForeignKey("licenses.id"), nullable=False)

    machine_id = Column(String(255), nullable=False, index=True)
    machine_name = Column(String(255), nullable=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    ip_address = Column(String(80), nullable=True)

    started_at = Column(DateTime, default=datetime.utcnow)
    last_heartbeat_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="active")

    license = relationship("License", back_populates="sessions")


class CaptchaUsage(Base):
    __tablename__ = "captcha_usage"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(80), unique=True, nullable=False, index=True)
    license_id = Column(Integer, ForeignKey("licenses.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("license_sessions.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=False, index=True)
    captcha_type = Column(String(40), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="processing", index=True)
    page_host = Column(String(180), nullable=True)
    sitekey_hash = Column(String(64), nullable=True)
    provider_task_id = Column(String(120), nullable=True)
    provider_cost = Column(String(50), nullable=True)
    client_ip = Column(String(80), nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    license = relationship("License")
    session = relationship("LicenseSession")


class LicenseCreditAccount(Base):
    __tablename__ = "license_credit_accounts"

    id = Column(Integer, primary_key=True, index=True)
    license_id = Column(Integer, ForeignKey("licenses.id"), unique=True, nullable=False, index=True)
    enabled = Column(Boolean, default=False, nullable=False)
    balance = Column(Integer, default=0, nullable=False)
    unit_price_cents = Column(Integer, default=500, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    license = relationship("License", back_populates="credit_account")
    ledger = relationship("CreditLedger", back_populates="account", cascade="all, delete-orphan")


class CreditEntitlement(Base):
    __tablename__ = "credit_entitlements"
    __table_args__ = (
        UniqueConstraint("license_id", "company_hash", "competence", name="uq_credit_entitlement"),
    )

    id = Column(Integer, primary_key=True, index=True)
    license_id = Column(Integer, ForeignKey("licenses.id"), nullable=False, index=True)
    company_hash = Column(String(64), nullable=False, index=True)
    competence = Column(String(7), nullable=False, index=True)
    company_alias = Column(String(80), nullable=True)
    company_name = Column(String(180), nullable=True)
    unlocked_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CreditQuote(Base):
    __tablename__ = "credit_quotes"

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(String(100), unique=True, nullable=False, index=True)
    reservation_id = Column(String(100), unique=True, nullable=True, index=True)
    license_id = Column(Integer, ForeignKey("licenses.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("license_sessions.id"), nullable=False, index=True)
    status = Column(String(20), default="quoted", nullable=False, index=True)
    total_items = Column(Integer, default=0, nullable=False)
    unlocked_items = Column(Integer, default=0, nullable=False)
    required_credits = Column(Integer, default=0, nullable=False)
    unit_price_cents = Column(Integer, default=500, nullable=False)
    balance_before = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
    reserved_at = Column(DateTime, nullable=True)
    committed_at = Column(DateTime, nullable=True)

    items = relationship("CreditQuoteItem", back_populates="quote", cascade="all, delete-orphan")


class CreditQuoteItem(Base):
    __tablename__ = "credit_quote_items"
    __table_args__ = (
        UniqueConstraint("quote_id", "company_hash", "competence", name="uq_credit_quote_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    quote_id = Column(Integer, ForeignKey("credit_quotes.id"), nullable=False, index=True)
    company_hash = Column(String(64), nullable=False)
    competence = Column(String(7), nullable=False)
    company_alias = Column(String(80), nullable=True)
    company_name = Column(String(180), nullable=True)
    is_new = Column(Boolean, default=True, nullable=False)

    quote = relationship("CreditQuote", back_populates="items")


class CreditLedger(Base):
    __tablename__ = "credit_ledger"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("license_credit_accounts.id"), nullable=False, index=True)
    delta = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    event_type = Column(String(30), nullable=False, index=True)
    reference = Column(String(120), nullable=True, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    account = relationship("LicenseCreditAccount", back_populates="ledger")


class CreditPurchase(Base):
    __tablename__ = "credit_purchases"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String(100), unique=True, nullable=False, index=True)
    payment_id = Column(String(100), unique=True, nullable=True, index=True)
    license_id = Column(Integer, ForeignKey("licenses.id"), nullable=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    customer_email = Column(String(150), nullable=False, index=True)
    customer_name = Column(String(150), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price_cents = Column(Integer, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String(20), default="pending", nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    paid_at = Column(DateTime, nullable=True)

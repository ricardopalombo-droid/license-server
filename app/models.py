from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
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
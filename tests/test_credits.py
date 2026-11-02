import os
import tempfile
import unittest
from base64 import b64encode
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request


handle, database_path = tempfile.mkstemp(prefix="palsys-credit-test-", suffix=".db")
os.close(handle)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.replace(os.sep, '/')}"
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LICENSE_API_TOKEN", "test-token")
os.environ["SMTP_HOST"] = ""
os.environ.setdefault("SMTP_USER", "test")
os.environ.setdefault("SMTP_PASSWORD", "test")
os.environ.setdefault("SMTP_FROM", "test@example.com")

from app.database import Base, SessionLocal, engine
from app.models import (
    Customer,
    CaptchaUsage,
    License,
    LicenseCreditAccount,
    LicenseSession,
    Product,
)
from app.routers.client_credits import commit, create_quote, create_store_access, reserve
from app.routers.webhook_mp import (
    confirm_credit_purchase,
    credit_customer_context,
    preview_credit_purchase,
)
from app.schemas import (
    CaptchaHcaptchaRequest,
    CaptchaImageRequest,
    CreditQuoteOperation,
    CreditQuoteRequest,
    CreditReservationOperation,
    CreditSessionRequest,
)
from app.routers.client_captcha import solve_nfe_hcaptcha, solve_sp_image


class CreditFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        customer = Customer(name="Teste", company="Empresa Teste", email="teste@example.com")
        product = Product(name="Auditor Integrado", code="22", is_active=True)
        captcha_product = Product(name="Buscador XML", code="20", is_active=True)
        db.add_all([customer, product, captcha_product])
        db.flush()
        license_obj = License(
            customer_id=customer.id,
            product_id=product.id,
            license_key="TESTE",
            plan_type="monthly",
            status="active",
            max_concurrent_sessions=1,
            grace_days=4,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(license_obj)
        db.flush()
        captcha_license = License(
            customer_id=customer.id,
            product_id=captcha_product.id,
            license_key="CAPTCHA-TESTE",
            plan_type="monthly",
            status="active",
            max_concurrent_sessions=1,
            grace_days=4,
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        db.add(captcha_license)
        db.flush()
        db.add_all([
            LicenseSession(
                license_id=license_obj.id,
                machine_id="machine",
                session_token="session",
                status="active",
            ),
            LicenseCreditAccount(
                license_id=license_obj.id,
                enabled=True,
                balance=5,
                unit_price_cents=500,
            ),
            LicenseSession(
                license_id=captcha_license.id,
                machine_id="captcha-machine",
                session_token="captcha-session-token",
                status="active",
            ),
        ])
        db.commit()
        db.close()
    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(database_path)
        except OSError:
            pass

    def test_first_processing_consumes_and_reprocessing_is_free(self):
        items = [{
            "company_key": "12345678000190",
            "company_alias": "0001",
            "company_name": "Empresa A",
            "competence": "2026-03",
        }]
        db = SessionLocal()
        try:
            quote = create_quote(CreditQuoteRequest(session_token="session", items=items), db)
            self.assertEqual(quote["required_credits"], 1)
            self.assertEqual(quote["credit_balance"], 5)

            reservation = reserve(
                CreditQuoteOperation(session_token="session", quote_id=quote["quote_id"]), db
            )
            self.assertEqual(reservation["credit_balance"], 4)

            result = commit(
                CreditReservationOperation(
                    session_token="session", reservation_id=reservation["reservation_id"]
                ),
                db,
            )
            self.assertTrue(result["ok"])

            reprocessing = create_quote(
                CreditQuoteRequest(session_token="session", items=items), db
            )
            self.assertEqual(reprocessing["required_credits"], 0)
            self.assertEqual(reprocessing["unlocked_items"], 1)
            self.assertEqual(reprocessing["credit_balance"], 4)
        finally:
            db.close()

    def test_app_store_access_identifies_license_without_typing_key(self):
        db = SessionLocal()
        try:
            access = create_store_access(CreditSessionRequest(session_token="session"), db)
            context = credit_customer_context(
                {"access_token": access["access_token"]}, db, "Bearer test-token"
            )
            self.assertEqual(context["customer_email"], "teste@example.com")
            self.assertIn("TESTE"[-6:], context["license_hint"])

            preview = preview_credit_purchase(
                {
                    "access_token": access["access_token"],
                    "product_code": "22",
                    "quantity": 2,
                },
                db,
                "Bearer test-token",
            )
            self.assertEqual(preview["customer_email"], "teste@example.com")
            self.assertEqual(preview["quantity"], 2)
        finally:
            db.close()

    def test_purchase_is_idempotent(self):
        db = SessionLocal()
        try:
            preview = preview_credit_purchase(
                {
                    "email": "cliente@example.com",
                    "name": "Cliente",
                    "license_key": "TESTE",
                    "product_code": "22",
                    "quantity": 3,
                },
                db,
                "Bearer test-token",
            )
            first = confirm_credit_purchase(
                {
                    "order_id": preview["order_id"],
                    "payment_id": "payment-1",
                    "status": "approved",
                    "amount_cents": preview["amount_cents"],
                },
                db,
                "Bearer test-token",
            )
            self.assertEqual(first["credits_added"], 3)
            second = confirm_credit_purchase(
                {
                    "order_id": preview["order_id"],
                    "payment_id": "payment-1",
                    "status": "approved",
                    "amount_cents": preview["amount_cents"],
                },
                db,
                "Bearer test-token",
            )
            self.assertEqual(second["action"], "duplicate_ignored")
            self.assertEqual(second["credit_balance"], first["credit_balance"])
        finally:
            db.close()

    def test_first_purchase_creates_credit_license(self):
        db = SessionLocal()
        try:
            preview = preview_credit_purchase(
                {
                    "email": "novo@example.com",
                    "name": "Novo Cliente",
                    "product_code": "22",
                    "quantity": 5,
                },
                db,
                "Bearer test-token",
            )
            result = confirm_credit_purchase(
                {
                    "order_id": preview["order_id"],
                    "payment_id": "payment-new",
                    "status": "approved",
                    "amount_cents": preview["amount_cents"],
                },
                db,
                "Bearer test-token",
            )
            self.assertTrue(result["license_key"])
            self.assertEqual(result["credit_balance"], 5)
            license_obj = db.query(License).filter(
                License.license_key == result["license_key"]
            ).first()
            self.assertEqual(license_obj.plan_type, "credits")
            self.assertEqual(license_obj.expires_at.year, 2099)
        finally:
            db.close()

    @staticmethod
    def _request():
        return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("127.0.0.1", 1234)})

    def test_captcha_proxy_uses_license_session_and_records_sp_consumption(self):
        # PNG 1x1 válido; o provedor é simulado para o teste não consumir saldo.
        png = b64encode(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
        ).decode("ascii")
        db = SessionLocal()
        try:
            with patch(
                "app.routers.client_captcha.solve_capmonster_image",
                return_value={"text": "ABC123", "task_id": "task-sp", "cost": "0.001"},
            ):
                result = solve_sp_image(
                    CaptchaImageRequest(
                        session_token="captcha-session-token",
                        context="sefaz_sp_nfe",
                        image_base64=png,
                    ),
                    self._request(),
                    db,
                )
            self.assertEqual(result["text"], "ABC123")
            usage = db.query(CaptchaUsage).filter(CaptchaUsage.provider_task_id == "task-sp").one()
            self.assertEqual(usage.status, "solved")
            self.assertEqual(usage.provider, "capmonster")
        finally:
            db.close()

    def test_captcha_proxy_allows_only_nfe_portal_for_nonecap(self):
        db = SessionLocal()
        try:
            with self.assertRaises(HTTPException) as blocked:
                solve_nfe_hcaptcha(
                    CaptchaHcaptchaRequest(
                        session_token="captcha-session-token",
                        page_url="https://example.com/portal/consultaRecaptcha.aspx",
                        sitekey="sitekey_teste_123",
                        user_agent="Mozilla/5.0 teste",
                    ),
                    self._request(),
                    db,
                )
            self.assertEqual(blocked.exception.status_code, 400)

            with patch(
                "app.routers.client_captcha.solve_nonecap_hcaptcha",
                return_value={"token": "token-resolvido", "response_key": "resp", "task_id": "task-nc", "cost": "1"},
            ):
                result = solve_nfe_hcaptcha(
                    CaptchaHcaptchaRequest(
                        session_token="captcha-session-token",
                        page_url=(
                            "https://www.nfe.fazenda.gov.br/portal/consultaRecaptcha.aspx"
                            "?tipoConsulta=resumo&tipoConteudo=teste"
                        ),
                        sitekey="sitekey_teste_123",
                        user_agent="Mozilla/5.0 teste",
                    ),
                    self._request(),
                    db,
                )
            self.assertEqual(result["token"], "token-resolvido")
            usage = db.query(CaptchaUsage).filter(CaptchaUsage.provider_task_id == "task-nc").one()
            self.assertEqual(usage.status, "solved")
            self.assertEqual(usage.provider, "nonecap")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

import os
import tempfile
import unittest
from datetime import datetime, timedelta


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
    License,
    LicenseCreditAccount,
    LicenseSession,
    Product,
)
from app.routers.client_credits import commit, create_quote, reserve
from app.routers.webhook_mp import confirm_credit_purchase, preview_credit_purchase
from app.schemas import CreditQuoteOperation, CreditQuoteRequest, CreditReservationOperation


class CreditFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        customer = Customer(name="Teste", company="Empresa Teste")
        product = Product(name="Auditor Integrado", code="22", is_active=True)
        db.add_all([customer, product])
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


if __name__ == "__main__":
    unittest.main()

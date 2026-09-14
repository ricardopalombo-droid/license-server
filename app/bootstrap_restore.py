from datetime import datetime

from app.database import SessionLocal
from app.models import AdminUser, Customer, Product, License


SEED_DATA = {
    "admin_users": [
        {
            "id": 1,
            "name": "Ricardo Palombo",
            "email": "ricardopalombo@bol.com.br",
            "password_hash": "$pbkdf2-sha256$29000$ImSsNeZ87z1n7P1/j7EWQg$hqoKRm3hAxa47C58E9Q2igyAVeJoT1f/hxNcSLJz5gQ",
            "is_active": 1,
            "created_at": "2026-04-18 19:01:06.207725",
        }
    ],
    "customers": [
        {
            "id": 1,
            "name": "Deublis",
            "company": "CONTCONNECT SOLUCOES CONTABEIS LTDA",
            "cpf_cnpj": "23.934.556/0001-50",
            "email": "ricardo.palombo@contconnect.com.br",
            "phone": None,
            "notes": None,
            "created_at": "2026-04-18 19:08:38.478349",
        },
        {
            "id": 2,
            "name": "Palsys",
            "company": "Palsys teste",
            "cpf_cnpj": None,
            "email": "ricardocontmatic@gmail.com",
            "phone": "12988175791",
            "notes": None,
            "created_at": "2026-04-21 15:31:57.246365",
        },
    ],
    "products": [
        {"id": 1, "name": "Cadastros de funcionários via planilha", "code": "1", "is_active": 1},
        {"id": 2, "name": "Fator R - Folha", "code": "2", "is_active": 1},
        {"id": 3, "name": "Receitas JR Phoenix para Folha", "code": "3", "is_active": 1},
        {"id": 4, "name": "Geração da SEDIF", "code": "4", "is_active": 1},
        {"id": 5, "name": "Benefícios da Folha", "code": "5", "is_active": 1},
        {"id": 6, "name": "Controle Receita MEI", "code": "6", "is_active": 1},
        {"id": 7, "name": "Análise Razão", "code": "7", "is_active": 1},
        {"id": 8, "name": "Conversor de Extratos", "code": "8", "is_active": 1},
        {"id": 9, "name": "Envio Automático de Documentos por WhatsApp", "code": "9", "is_active": 1},
        {"id": 10, "name": "Apuração DRE + Reinf R-4000", "code": "10", "is_active": 1},
        {"id": 11, "name": "Envio Automático de Documentos por E-mail", "code": "11", "is_active": 1},
        {"id": 12, "name": "Importação guia rápida - FGTS Digital", "code": "12", "is_active": 1},
        {"id": 13, "name": "eCAC / Recibos REINF e DCTFWeb", "code": "13", "is_active": 1},
        {"id": 14, "name": "PalSys - Consulta DCTFWeb - Integra Contador", "code": "14", "is_active": 1},
        {"id": 15, "name": "PDF Monitor", "code": "15", "is_active": 1},
        {"id": 16, "name": "Cadastro automatizado de funcionários", "code": "16", "is_active": 1},
        {"id": 17, "name": "Consolida Impostos", "code": "17", "is_active": 1},
        {"id": 18, "name": "Consolidador de Folhas", "code": "18", "is_active": 1},
    ],
    "licenses": [
        {
            "id": 1,
            "customer_id": 2,
            "product_id": 9,
            "license_key": "15BD-40C1-6E9B-7DE1",
            "plan_type": "monthly",
            "status": "active",
            "max_concurrent_sessions": 1,
            "grace_days": 4,
            "issued_at": "2026-04-21 15:35:23.943846",
            "expires_at": "2026-05-21 15:35:23.940447",
            "last_validation_at": "2026-04-21 16:04:00.758595",
            "notes": None,
            "mp_subscription_id": None,
            "mp_last_payment_id": None,
        },
        {
            "id": 2,
            "customer_id": 2,
            "product_id": 11,
            "license_key": "4230-9A9B-A7B1-C68F",
            "plan_type": "monthly",
            "status": "active",
            "max_concurrent_sessions": 1,
            "grace_days": 4,
            "issued_at": "2026-04-21 15:36:10.549382",
            "expires_at": "2026-05-21 15:36:10.548355",
            "last_validation_at": "2026-04-21 15:42:17.976576",
            "notes": None,
            "mp_subscription_id": None,
            "mp_last_payment_id": None,
        },
        {
            "id": 3,
            "customer_id": 2,
            "product_id": 10,
            "license_key": "B23F-EEC5-D0B7-D02F",
            "plan_type": "monthly",
            "status": "active",
            "max_concurrent_sessions": 1,
            "grace_days": 4,
            "issued_at": "2026-04-21 18:53:44.772840",
            "expires_at": "2026-05-21 18:53:44.768407",
            "last_validation_at": "2026-04-23 14:09:36.952862",
            "notes": None,
            "mp_subscription_id": None,
            "mp_last_payment_id": None,
        },
        {
            "id": 4,
            "customer_id": 2,
            "product_id": 12,
            "license_key": "46C3-F32B-F70B-54CB",
            "plan_type": "monthly",
            "status": "active",
            "max_concurrent_sessions": 1,
            "grace_days": 4,
            "issued_at": "2026-04-21 21:36:23.053537",
            "expires_at": "2026-05-21 21:36:23.052537",
            "last_validation_at": "2026-04-21 22:12:34.308561",
            "notes": None,
            "mp_subscription_id": None,
            "mp_last_payment_id": None,
        },
        {
            "id": 5,
            "customer_id": 2,
            "product_id": 13,
            "license_key": "6B3D-A02D-6E0C-CDCC",
            "plan_type": "monthly",
            "status": "active",
            "max_concurrent_sessions": 1,
            "grace_days": 4,
            "issued_at": "2026-04-22 14:07:15.283660",
            "expires_at": "2026-05-22 14:07:15.279859",
            "last_validation_at": "2026-04-22 17:48:47.743581",
            "notes": None,
            "mp_subscription_id": None,
            "mp_last_payment_id": None,
        },
    ],
}


def _parse_dt(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value)


def ensure_site_products(db):
    """Mantém cadastrados os produtos exibidos na página de assinatura."""
    for item in SEED_DATA["products"]:
        product = db.query(Product).filter(Product.code == item["code"]).first()
        if product:
            product.name = item["name"]
            product.is_active = bool(item["is_active"])
            continue

        product = Product(
            name=item["name"],
            code=item["code"],
            is_active=bool(item["is_active"]),
        )
        db.add(product)


def merge_duplicate_dctfweb_product(db):
    """
    Produto 19 foi criado como duplicado do produto 14.
    Mantém as licenças existentes, apenas troca o vínculo para o produto correto.
    """
    product_14 = db.query(Product).filter(Product.code == "14").first()
    product_19 = db.query(Product).filter(Product.code == "19").first()
    if not product_14 or not product_19:
        return

    db.query(License).filter(License.product_id == product_19.id).update(
        {License.product_id: product_14.id},
        synchronize_session=False,
    )
    product_19.is_active = False
    product_19.name = "ECAC - Integra Contador (unificado no produto 14)"


def restore_initial_data_if_empty():
    db = SessionLocal()
    try:
        if db.query(AdminUser).count() == 0:
            db.add_all(
                [
                    AdminUser(
                        id=item["id"],
                        name=item["name"],
                        email=item["email"],
                        password_hash=item["password_hash"],
                        is_active=bool(item["is_active"]),
                        created_at=_parse_dt(item["created_at"]),
                    )
                    for item in SEED_DATA["admin_users"]
                ]
            )

        if db.query(Customer).count() == 0:
            db.add_all(
                [
                    Customer(
                        id=item["id"],
                        name=item["name"],
                        company=item["company"],
                        cpf_cnpj=item["cpf_cnpj"],
                        email=item["email"],
                        phone=item["phone"],
                        notes=item["notes"],
                        created_at=_parse_dt(item["created_at"]),
                    )
                    for item in SEED_DATA["customers"]
                ]
            )

        if db.query(Product).count() == 0:
            db.add_all(
                [
                    Product(
                        id=item["id"],
                        name=item["name"],
                        code=item["code"],
                        is_active=bool(item["is_active"]),
                    )
                    for item in SEED_DATA["products"]
                ]
            )

        db.commit()
        ensure_site_products(db)
        merge_duplicate_dctfweb_product(db)
        db.commit()

        if db.query(License).count() == 0:
            db.add_all(
                [
                    License(
                        id=item["id"],
                        customer_id=item["customer_id"],
                        product_id=item["product_id"],
                        license_key=item["license_key"],
                        plan_type=item["plan_type"],
                        status=item["status"],
                        max_concurrent_sessions=item["max_concurrent_sessions"],
                        grace_days=item["grace_days"],
                        issued_at=_parse_dt(item["issued_at"]),
                        expires_at=_parse_dt(item["expires_at"]),
                        last_validation_at=_parse_dt(item["last_validation_at"]),
                        notes=item["notes"],
                        mp_subscription_id=item["mp_subscription_id"],
                        mp_last_payment_id=item["mp_last_payment_id"],
                    )
                    for item in SEED_DATA["licenses"]
                ]
            )
            db.commit()
    finally:
        db.close()

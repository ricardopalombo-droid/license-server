from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.dependencies import get_db, get_current_admin
from app.models import AdminUser, Customer, Product, License, LicenseSession
from app.utils import generate_license_key, plan_expiration
from app.config import settings
from app.security import get_password_hash

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="app/templates")


def redirect_login():
    return RedirectResponse(url="/login", status_code=302)


def safe_admin(request: Request, db: Session):
    try:
        return get_current_admin(request, db)
    except Exception:
        return None


def cleanup_expired_sessions(db: Session):
    limit = datetime.utcnow() - timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES)
    sessions = db.query(LicenseSession).filter(
        LicenseSession.status == "active",
        LicenseSession.last_heartbeat_at < limit,
    ).all()

    changed = False
    for s in sessions:
        s.status = "timeout"
        s.ended_at = datetime.utcnow()
        changed = True

    if changed:
        db.commit()


@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    cleanup_expired_sessions(db)

    total_customers = db.query(func.count(Customer.id)).scalar() or 0
    total_products = db.query(func.count(Product.id)).scalar() or 0
    total_licenses = db.query(func.count(License.id)).scalar() or 0
    active_licenses = db.query(func.count(License.id)).filter(License.status == "active").scalar() or 0
    blocked_licenses = db.query(func.count(License.id)).filter(License.status == "blocked").scalar() or 0
    active_sessions = db.query(func.count(LicenseSession.id)).filter(LicenseSession.status == "active").scalar() or 0

    recent_licenses = db.query(License).order_by(License.id.desc()).limit(10).all()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "admin": admin,
            "total_customers": total_customers,
            "total_products": total_products,
            "total_licenses": total_licenses,
            "active_licenses": active_licenses,
            "blocked_licenses": blocked_licenses,
            "active_sessions": active_sessions,
            "recent_licenses": recent_licenses,
        },
    )


@router.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    customers = db.query(Customer).order_by(Customer.id.desc()).all()
    return templates.TemplateResponse(
        "customers.html",
        {"request": request, "admin": admin, "customers": customers},
    )


@router.post("/customers")
def customers_create(
    request: Request,
    name: str = Form(...),
    company: str = Form(""),
    cpf_cnpj: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    customer = Customer(
        name=name.strip(),
        company=company.strip() or None,
        cpf_cnpj=cpf_cnpj.strip() or None,
        email=email.strip() or None,
        phone=phone.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(customer)
    db.commit()
    return RedirectResponse(url="/admin/customers", status_code=302)


@router.get("/customers/{customer_id}/edit", response_class=HTMLResponse)
def customers_edit_page(customer_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/admin/customers", status_code=302)

    return templates.TemplateResponse(
        "customer_edit.html",
        {"request": request, "admin": admin, "customer": customer},
    )


@router.post("/customers/{customer_id}/update")
def customers_update(
    customer_id: int,
    request: Request,
    name: str = Form(...),
    company: str = Form(""),
    cpf_cnpj: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/admin/customers", status_code=302)

    customer.name = name.strip()
    customer.company = company.strip() or None
    customer.cpf_cnpj = cpf_cnpj.strip() or None
    customer.email = email.strip() or None
    customer.phone = phone.strip() or None
    customer.notes = notes.strip() or None
    db.commit()

    return RedirectResponse(url="/admin/customers", status_code=302)


@router.post("/customers/{customer_id}/delete")
def customers_delete(customer_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return RedirectResponse(url="/admin/customers", status_code=302)

    has_licenses = db.query(License).filter(License.customer_id == customer_id).first()
    if has_licenses:
        return RedirectResponse(url="/admin/customers", status_code=302)

    db.delete(customer)
    db.commit()
    return RedirectResponse(url="/admin/customers", status_code=302)


@router.post("/reset-password")
def reset_admin_password(
    request: Request,
    email: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    user = db.query(AdminUser).filter(AdminUser.email == email.strip()).first()
    if user:
        user.password_hash = get_password_hash(new_password.strip())
        db.commit()

    return RedirectResponse(url="/admin", status_code=302)

@router.get("/products", response_class=HTMLResponse)
def products_page(request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    products = db.query(Product).order_by(Product.id.desc()).all()
    edit_product_id = request.query_params.get("edit")
    product_to_edit = None

    if edit_product_id:
        try:
            product_to_edit = db.query(Product).filter(Product.id == int(edit_product_id)).first()
        except Exception:
            product_to_edit = None

    return templates.TemplateResponse(
        "products.html",
        {
            "request": request,
            "admin": admin,
            "products": products,
            "product_to_edit": product_to_edit,
        },
    )


@router.post("/products")
def products_create(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    code_clean = code.strip().upper()
    existing = db.query(Product).filter(Product.code == code_clean).first()

    if not existing:
        product = Product(
            name=name.strip(),
            code=code_clean,
            is_active=True,
        )
        db.add(product)
        db.commit()

    return RedirectResponse(url="/admin/products", status_code=302)


@router.post("/products/{product_id}/update")
def products_update(
    product_id: int,
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse(url="/admin/products", status_code=302)

    code_clean = code.strip().upper()

    existing_same_code = (
        db.query(Product)
        .filter(Product.code == code_clean, Product.id != product_id)
        .first()
    )
    if existing_same_code:
        return RedirectResponse(url=f"/admin/products?edit={product_id}", status_code=302)

    product.name = name.strip()
    product.code = code_clean
    db.commit()

    return RedirectResponse(url="/admin/products", status_code=302)


@router.post("/products/{product_id}/toggle-active")
def products_toggle_active(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.is_active = not product.is_active
        db.commit()

    return RedirectResponse(url="/admin/products", status_code=302)


@router.post("/products/{product_id}/delete")
def products_delete(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return RedirectResponse(url="/admin/products", status_code=302)

    has_licenses = db.query(License).filter(License.product_id == product_id).first()
    if has_licenses:
        return RedirectResponse(url="/admin/products", status_code=302)

    db.delete(product)
    db.commit()

    return RedirectResponse(url="/admin/products", status_code=302)



@router.get("/licenses", response_class=HTMLResponse)
def licenses_page(request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    cleanup_expired_sessions(db)
    licenses = db.query(License).order_by(License.id.desc()).all()

    return templates.TemplateResponse(
        "licenses.html",
        {"request": request, "admin": admin, "licenses": licenses},
    )


@router.get("/licenses/new", response_class=HTMLResponse)
def licenses_new_page(request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    customers = db.query(Customer).order_by(Customer.name.asc()).all()
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.name.asc()).all()

    return templates.TemplateResponse(
        "license_form.html",
        {"request": request, "admin": admin, "customers": customers, "products": products},
    )


@router.post("/licenses/new")
def licenses_create(
    request: Request,
    customer_id: int = Form(...),
    product_id: int = Form(...),
    plan_type: str = Form(...),
    max_concurrent_sessions: int = Form(...),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    license_obj = License(
        customer_id=customer_id,
        product_id=product_id,
        license_key=generate_license_key(),
        plan_type=plan_type,
        status="active",
        max_concurrent_sessions=max_concurrent_sessions,
        grace_days=settings.OFFLINE_GRACE_DAYS,
        expires_at=plan_expiration(plan_type),
        notes=notes.strip() or None,
    )
    db.add(license_obj)
    db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)


@router.get("/licenses/{license_id}/edit", response_class=HTMLResponse)
def licenses_edit_page(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if not lic:
        return RedirectResponse(url="/admin/licenses", status_code=302)

    return templates.TemplateResponse(
        "license_edit.html",
        {"request": request, "admin": admin, "license": lic},
    )


@router.post("/licenses/{license_id}/update")
def licenses_update(
    license_id: int,
    request: Request,
    license_key: str = Form(...),
    plan_type: str = Form(...),
    status: str = Form(...),
    max_concurrent_sessions: int = Form(...),
    grace_days: int = Form(...),
    expires_at_date: str = Form(...),
    adjust_days: int = Form(0),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if not lic:
        return RedirectResponse(url="/admin/licenses", status_code=302)

    normalized_key = license_key.strip().upper()
    existing_same_key = (
        db.query(License)
        .filter(License.license_key == normalized_key, License.id != license_id)
        .first()
    )
    if existing_same_key:
        return RedirectResponse(url=f"/admin/licenses/{license_id}/edit?error=license_key", status_code=302)

    try:
        parsed_date = datetime.strptime(expires_at_date.strip(), "%Y-%m-%d")
    except ValueError:
        return RedirectResponse(url=f"/admin/licenses/{license_id}/edit?error=expires_at", status_code=302)

    current_expiration = lic.expires_at or datetime.utcnow()
    updated_expiration = parsed_date.replace(
        hour=current_expiration.hour,
        minute=current_expiration.minute,
        second=current_expiration.second,
        microsecond=current_expiration.microsecond,
    )
    if adjust_days:
        updated_expiration = updated_expiration + timedelta(days=adjust_days)

    lic.license_key = normalized_key
    lic.plan_type = plan_type
    lic.status = status
    lic.max_concurrent_sessions = max_concurrent_sessions
    lic.grace_days = grace_days
    lic.expires_at = updated_expiration
    lic.notes = notes.strip() or None
    db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)


@router.post("/licenses/{license_id}/block")
def block_license(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if lic:
        lic.status = "blocked"
        db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)


@router.post("/licenses/{license_id}/unblock")
def unblock_license(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if lic:
        lic.status = "active"
        db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)


@router.post("/licenses/{license_id}/renew-monthly")
def renew_monthly(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if lic:
        base_date = lic.expires_at if lic.expires_at and lic.expires_at > datetime.utcnow() else datetime.utcnow()
        lic.plan_type = "monthly"
        lic.expires_at = base_date + timedelta(days=30)
        if lic.status in ("expired", "blocked", "revoked"):
            lic.status = "active"
        db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)


@router.post("/licenses/{license_id}/renew-annual")
def renew_annual(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if lic:
        base_date = lic.expires_at if lic.expires_at and lic.expires_at > datetime.utcnow() else datetime.utcnow()
        lic.plan_type = "annual"
        lic.expires_at = base_date + timedelta(days=365)
        if lic.status in ("expired", "blocked", "revoked"):
            lic.status = "active"
        db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)


@router.get("/licenses/{license_id}/sessions", response_class=HTMLResponse)
def license_sessions(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    cleanup_expired_sessions(db)
    lic = db.query(License).filter(License.id == license_id).first()
    if not lic:
        return RedirectResponse(url="/admin/licenses", status_code=302)

    sessions = (
        db.query(LicenseSession)
        .filter(LicenseSession.license_id == license_id)
        .order_by(LicenseSession.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "sessions.html",
        {"request": request, "admin": admin, "license": lic, "sessions": sessions},
    )


@router.post("/licenses/{license_id}/close-all-sessions")
def close_all_sessions(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    sessions = db.query(LicenseSession).filter(
        LicenseSession.license_id == license_id,
        LicenseSession.status == "active"
    ).all()

    for s in sessions:
        s.status = "closed"
        s.ended_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(url=f"/admin/licenses/{license_id}/sessions", status_code=302)


@router.post("/sessions/{session_id}/close")
def close_session(session_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    session = db.query(LicenseSession).filter(LicenseSession.id == session_id).first()
    redirect_id = session.license_id if session else 0

    if session and session.status == "active":
        session.status = "closed"
        session.ended_at = datetime.utcnow()
        db.commit()

    return RedirectResponse(url=f"/admin/licenses/{redirect_id}/sessions", status_code=302)

@router.post("/licenses/{license_id}/delete")
def delete_license(license_id: int, request: Request, db: Session = Depends(get_db)):
    admin = safe_admin(request, db)
    if not admin:
        return redirect_login()

    lic = db.query(License).filter(License.id == license_id).first()
    if not lic:
        return RedirectResponse(url="/admin/licenses", status_code=302)

    # Verifica se há sessões ativas
    active_sessions = db.query(LicenseSession).filter(
        LicenseSession.license_id == license_id,
        LicenseSession.status == "active"
    ).first()

    if active_sessions:
        # não permite excluir se houver sessão ativa
        return RedirectResponse(url="/admin/licenses", status_code=302)

    # Remove sessões antigas (histórico)
    db.query(LicenseSession).filter(
        LicenseSession.license_id == license_id
    ).delete()

    # Remove a licença
    db.delete(lic)
    db.commit()

    return RedirectResponse(url="/admin/licenses", status_code=302)

from fastapi import Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.security import decode_access_token
from app.config import settings
from app.models import AdminUser


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    token = request.cookies.get(settings.ADMIN_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=302, detail="Não autenticado")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=302, detail="Token inválido")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=302, detail="Token inválido")

    user = db.query(AdminUser).filter(AdminUser.id == int(user_id), AdminUser.is_active == True).first()
    if not user:
        raise HTTPException(status_code=302, detail="Usuário inválido")

    return user

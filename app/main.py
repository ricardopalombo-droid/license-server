from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import engine, Base
from app.routers import admin_auth, admin_web, client_license, webhook_mp
from app.config import settings

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.APP_NAME)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(admin_auth.router)
app.include_router(admin_web.router)
app.include_router(client_license.router)
app.include_router(webhook_mp.router)


@app.get("/")
def root():
    return {
        "app": settings.APP_NAME,
        "admin": "/login",
        "client_api": "/client/activate",
        "webhook_mp": "/webhook/mercadopago",
    }
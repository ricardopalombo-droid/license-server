from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Licenca Server"
    DATABASE_URL: str = "sqlite:////data/licencas.db"

    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ADMIN_COOKIE_NAME: str = "admin_token"
    ADMIN_COOKIE_SECURE: bool = True
    ADMIN_COOKIE_SAMESITE: str = "strict"

    SESSION_TIMEOUT_MINUTES: int = 10
    OFFLINE_GRACE_DAYS: int = 4
    AUDITOR_CREDIT_PRICE_CENTS: int = 500

    # Captchas do Buscador XML (produto 20). As chaves ficam somente no servidor.
    CAPMONSTER_API_KEY: str = ""
    NONECAP_API_KEY: str = ""
    CAPTCHA_PRODUCT_CODE: str = "20"
    CAPTCHA_RATE_LIMIT_PER_HOUR: int = 1000
    CAPTCHA_MAX_CONCURRENT_PER_LICENSE: int = 5
    CAPTCHA_MAX_CONCURRENT_GLOBAL: int = 25
    CAPTCHA_REQUEST_TIMEOUT_SECONDS: int = 150

    # SEGURANÇA WEBHOOK
    LICENSE_API_TOKEN: str

    # 🔥 ADICIONE ISSO AQUI
    LICENSE_SIGN_PRIVATE_KEY: str | None = None

    # EMAIL
    SMTP_HOST: str
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_FROM: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

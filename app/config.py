from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Licenca Server"
    DATABASE_URL: str = "sqlite:////data/licencas.db"

    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ADMIN_COOKIE_NAME: str = "admin_token"

    SESSION_TIMEOUT_MINUTES: int = 10
    OFFLINE_GRACE_DAYS: int = 4

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

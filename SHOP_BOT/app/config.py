"""Konfiguratsiya: .env faylidan o'qiladi va tekshiriladi (pydantic-settings)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────
    bot_token: SecretStr = Field(default=SecretStr(""), description="BotFather tokeni")
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    bot_username: str | None = None

    # ── Infratuzilma ──────────────────────────────────────────
    db_url: str = "postgresql+asyncpg://shopbot:shopbot@postgres:5432/shopbot"
    redis_url: str = "redis://redis:6379/0"

    # ── Ish rejimi ────────────────────────────────────────────
    run_mode: Literal["bot", "poster", "all"] = "all"
    use_webhook: bool = False
    webhook_base_url: str = ""
    webhook_path: str = "/webhook"
    webhook_secret: SecretStr = SecretStr("change-me")

    # ── Health server ─────────────────────────────────────────
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    health_token: SecretStr | None = None

    # ── Umumiy ────────────────────────────────────────────────
    log_level: str = "INFO"
    log_dir: str = "logs"
    timezone: str = "Asia/Tashkent"
    sentry_dsn: str | None = None
    # Dev rejimi: Redis bo'lmasa MemoryStorage'ga tushish, qo'shimcha loglar
    dev_mode: bool = False

    # ── Validatsiya ───────────────────────────────────────────
    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> Any:
        """ADMIN_IDS="111,222" yoki "111 222" ko'rinishini ro'yxatga aylantiradi."""
        if value is None or value == "":
            return []
        if isinstance(value, str):
            cleaned = value.replace(";", ",").replace(" ", ",")
            return [int(part) for part in cleaned.split(",") if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [int(v) for v in value]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()

    # ── Yordamchi xossalar ────────────────────────────────────
    @property
    def token(self) -> str:
        return self.bot_token.get_secret_value()

    @property
    def webhook_secret_value(self) -> str:
        return self.webhook_secret.get_secret_value()

    @property
    def is_sqlite(self) -> bool:
        return self.db_url.startswith("sqlite")

    @property
    def is_webhook_ready(self) -> bool:
        return bool(self.use_webhook and self.webhook_base_url and self.token)

    @property
    def webhook_url(self) -> str:
        return f"{self.webhook_base_url.rstrip('/')}{self.webhook_path}"

    def validate_for_bot(self) -> None:
        """Bot rejimida ishga tushishdan oldin majburiy maydonlarni tekshirish."""
        problems: list[str] = []
        if not self.token:
            problems.append("BOT_TOKEN bo'sh")
        if not self.admin_ids:
            problems.append("ADMIN_IDS bo'sh (super admin kerak)")
        if self.use_webhook and not self.webhook_base_url:
            problems.append("USE_WEBHOOK=true, lekin WEBHOOK_BASE_URL ko'rsatilmagan")
        if self.use_webhook and self.webhook_secret_value in ("", "change-me"):
            problems.append("USE_WEBHOOK=true, lekin WEBHOOK_SECRET o'zgartirilmagan")
        if problems:
            raise RuntimeError("Konfiguratsiya xatosi: " + "; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Sozlamalar keshini qaytaradi (bir marta o'qiladi)."""
    return Settings()


def reset_settings_cache() -> None:
    """Testlarda .env ni qayta o'qish uchun."""
    get_settings.cache_clear()

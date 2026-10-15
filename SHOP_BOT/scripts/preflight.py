"""Production Docker Compose konfiguratsiyasini TARMOQSIZ tekshirish.

Haqiqiy DB, Redis, Telegram yoki TLS mavjudligini tekshirmaydi. Maxfiy
qiymatlar hech qachon chiqishga yozilmaydi. Ishlatish: python3 -m scripts.preflight
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

REQUIRED = (
    "BOT_TOKEN", "ADMIN_IDS", "DB_URL", "REDIS_URL", "POSTGRES_USER",
    "POSTGRES_PASSWORD", "POSTGRES_DB", "HEALTH_TOKEN", "USE_WEBHOOK",
)


def read_env(path: Path) -> dict[str, str]:
    """Oddiy KEY=VALUE formatini o'qiydi, fayldagi kodni ishga tushirmaydi."""
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            raise ValueError(f".env qator {number}: KEY=VALUE kutilgan")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", key):
            raise ValueError(f".env qator {number}: noto'g'ri kalit")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key in values:
            raise ValueError(f".env qator {number}: takror kalit {key}")
        values[key] = value
    return values


def check(values: dict[str, str]) -> list[str]:
    """Xatolar ro'yxati: token/parolni qaytarmaydi, faqat maydon nomlarini."""
    problems = [f"{key}: ko'rsatilmagan" for key in REQUIRED if not values.get(key)]
    token = values.get("BOT_TOKEN", "")
    if token and not re.fullmatch(r"[0-9]{5,}:[A-Za-z0-9_-]{35,}", token):
        problems.append("BOT_TOKEN: @BotFather bergan token formatida emas")

    admins = values.get("ADMIN_IDS", "")
    if admins:
        ids = admins.replace(";", ",").replace(" ", ",").split(",")
        if any(not item.isdigit() or int(item) in (0, 123456789) for item in ids):
            problems.append("ADMIN_IDS: haqiqiy raqamli admin ID(lar)ni kiriting")

    password = values.get("POSTGRES_PASSWORD", "")
    if password and (len(password) < 16 or "$" in password or password.lower().startswith("change")):
        problems.append("POSTGRES_PASSWORD: 16+ belgili noyob parol kiriting ($ belgisisiz)")
    for key in ("HEALTH_TOKEN", "WEBHOOK_SECRET"):
        secret = values.get(key, "")
        if key == "WEBHOOK_SECRET" and values.get("USE_WEBHOOK") != "true":
            continue
        if secret and (len(secret) < 24 or secret.lower().startswith("change")):
            problems.append(f"{key}: kamida 24 belgili noyob sir kiriting")

    db_url = values.get("DB_URL", "")
    if db_url:
        try:
            url = urlsplit(db_url)
            if (url.scheme != "postgresql+asyncpg" or url.hostname != "postgres"
                    or unquote(url.username or "") != values.get("POSTGRES_USER")
                    or unquote(url.password or "") != password
                    or unquote(url.path.lstrip("/")) != values.get("POSTGRES_DB")):
                problems.append("DB_URL: Compose postgres servisi va POSTGRES_* bilan mos bo'lishi kerak")
        except ValueError:
            problems.append("DB_URL: noto'g'ri URL")
    redis_url = values.get("REDIS_URL", "")
    if redis_url:
        try:
            url = urlsplit(redis_url)
            if url.scheme != "redis" or url.hostname != "redis":
                problems.append("REDIS_URL: Compose redis servisiga yo'naltirilishi kerak")
        except ValueError:
            problems.append("REDIS_URL: noto'g'ri URL")

    use_webhook = values.get("USE_WEBHOOK", "")
    if use_webhook not in ("true", "false"):
        problems.append("USE_WEBHOOK: true yoki false bo'lishi kerak")
    if use_webhook == "true":
        domain = values.get("DOMAIN", "")
        base = values.get("WEBHOOK_BASE_URL", "")
        try:
            url = urlsplit(base)
            if (not domain or "example" in domain or "sizning-domeningiz" in domain
                    or url.scheme != "https" or url.hostname != domain
                    or url.path not in ("", "/") or url.query or url.fragment
                    or values.get("WEBHOOK_PATH") != "/webhook"):
                problems.append("DOMAIN/WEBHOOK_BASE_URL/WEBHOOK_PATH: HTTPS domen va /webhook mos bo'lishi kerak")
        except ValueError:
            problems.append("WEBHOOK_BASE_URL: noto'g'ri URL")
        if not values.get("WEBHOOK_SECRET"):
            problems.append("WEBHOOK_SECRET: ko'rsatilmagan")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose deploy konfiguratsiyasini oflayn tekshirish")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    args = parser.parse_args()
    try:
        values = read_env(args.env)
        problems = check(values)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"❌ .env o'qilmadi: {exc}")
        return 1
    if problems:
        for problem in problems:
            print(f"❌ {problem}")
        return 1
    print("✅ Oflayn konfiguratsiya tekshiruvi o'tdi (jonli servislar tekshirilmadi).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

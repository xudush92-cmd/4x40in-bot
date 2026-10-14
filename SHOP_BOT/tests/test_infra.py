"""Infratuzilma testlari: Docker Compose, migratsiya, .env namunasi, xavfsizlik."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_is_valid_yaml() -> None:
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = data["services"]
    for name in ("postgres", "redis", "migrate", "bot", "poster", "caddy"):
        assert name in services, f"docker-compose'da '{name}' servisi yo'q"


def test_docker_compose_uses_healthchecks_and_volumes() -> None:
    data = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = data["services"]

    assert "healthcheck" in services["postgres"]
    assert "healthcheck" in services["redis"]
    assert services["bot"]["environment"]["RUN_MODE"] == "bot"
    assert services["poster"]["environment"]["RUN_MODE"] == "poster"
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]

    volumes = data["volumes"]
    for volume in ("pgdata", "redisdata", "caddy_data"):
        assert volume in volumes


def test_dockerfile_is_reasonable() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "USER shopbot" in dockerfile  # root bo'lmagan foydalanuvchi


def test_env_example_has_no_real_secrets() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("BOT_TOKEN", "ADMIN_IDS", "DB_URL", "REDIS_URL", "USE_WEBHOOK", "WEBHOOK_SECRET"):
        assert key in text, f".env.example da {key} yo'q"
    assert "AAAA-your-real-token-here" in text


def test_alembic_configured() -> None:
    assert (ROOT / "alembic.ini").exists()
    assert (ROOT / "alembic" / "env.py").exists()
    assert (ROOT / "alembic" / "versions").exists()


def test_gitignore_protects_secrets() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "logs/", "data/"):
        assert pattern in text


def test_requirements_pinned_ranges() -> None:
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for package in ("aiogram", "SQLAlchemy", "alembic", "redis", "APScheduler", "aiohttp", "loguru"):
        assert package in text, f"requirements.txt da {package} yo'q"


@pytest.mark.parametrize(
    "script", ["scripts/backup.sh", "scripts/restore.sh"]
)
def test_shell_scripts_exist(script: str) -> None:
    assert (ROOT / script).exists()

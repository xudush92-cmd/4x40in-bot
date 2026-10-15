"""Phase 9: production preflight, backup/restore xavfsizligi (Docker mock, jonli DB EMAS)."""

from __future__ import annotations

import gzip
import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.preflight import check, read_env

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def good_env() -> dict[str, str]:
    data = read_env(ROOT / ".env.example")
    data.update({
        "BOT_TOKEN": "123456:" + "a" * 40,
        "ADMIN_IDS": "876543210",
        "POSTGRES_PASSWORD": "secure-test-password-123",
        "DB_URL": "postgresql+asyncpg://shopbot:secure-test-password-123@postgres:5432/shopbot",
        "HEALTH_TOKEN": "private-health-test-token-12345",
        "USE_WEBHOOK": "false",
    })
    return data


def test_preflight_rejects_template_and_accepts_complete_config(good_env):
    errors = check(read_env(ROOT / ".env.example"))
    assert "BOT_TOKEN" in str(errors) and "POSTGRES_PASSWORD" in str(errors)
    assert "ADMIN_IDS" in str(errors)
    assert check(good_env) == []
    good_env.update({
        "USE_WEBHOOK": "true", "DOMAIN": "bot.real-domain.uz",
        "WEBHOOK_BASE_URL": "https://bot.real-domain.uz",
        "WEBHOOK_SECRET": "webhook-secret-for-test-only-45678",
    })
    assert check(good_env) == []
    good_env["WEBHOOK_BASE_URL"] = "http://not-the-domain.uz"
    assert "DOMAIN/WEBHOOK_BASE_URL" in str(check(good_env))


def test_preflight_rejects_db_password_mismatch_without_echoing_secrets(good_env):
    good_env["POSTGRES_PASSWORD"] = "another-secure-password-234"
    errors = check(good_env)
    assert any("DB_URL" in item for item in errors)
    assert not any("another-secure-password-234" in item for item in errors)


def test_read_env_rejects_duplicate_or_shell_syntax(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ADMIN_IDS=42\nADMIN_IDS=43\n")
    with pytest.raises(ValueError, match="takror"):
        read_env(path)
    path.write_text("$(evil command)\n")
    with pytest.raises(ValueError, match="KEY=VALUE"):
        read_env(path)


@pytest.fixture
def fake_docker(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "$MOCK_DOCKER_LOG"
case "$1" in
  ps)
    if [[ "${MOCK_NO_CONTAINER:-0}" == 1 ]]; then exit 0; fi
    printf 'shopbot-postgres\\n'
    if [[ "${MOCK_WORKERS_RUNNING:-0}" == 1 ]]; then
      printf 'shopbot-bot\\nshopbot-poster\\n'
    fi;;
  exec)
    method="${3:-}"
    if [[ "${2:-}" == "-i" ]]; then method="${4:-}"; fi
    if [[ "$method" == "pg_dump" ]]; then
      printf 'DROP TABLE IF EXISTS mock;\\nCREATE TABLE mock (id int);\\n'
      if [[ "${MOCK_FAIL_DUMP:-0}" == 1 ]]; then exit 7; fi
    elif [[ "$method" == "psql" ]]; then
      cat > "$MOCK_RESTORE_OUTPUT"
      if [[ "${MOCK_FAIL_PSQL:-0}" == 1 ]]; then exit 8; fi
    else exit 9; fi;;
  compose)
    case "${2:-}" in version) exit 0;; esac
    case "${*: -1}" in *) exit 0;; esac;;
  *) exit 10;;
esac
""")
    docker.chmod(0o755)
    env = os.environ.copy()
    env.update({
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MOCK_DOCKER_LOG": str(tmp_path / "docker.log"),
        "MOCK_RESTORE_OUTPUT": str(tmp_path / "restored.sql"),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "POSTGRES_CONTAINER": "shopbot-postgres",
    })
    return env


def _run(script: str, tmp_path: Path, env: dict[str, str], *args: str, input: str = ""):
    return subprocess.run(
        ["bash", str(ROOT / "scripts" / script), *args], cwd=tmp_path,
        env=env, input=input, text=True, capture_output=True, check=False,
    )


def test_backup_atomic_private_and_partial_dump_cleaned(tmp_path, fake_docker):
    result = _run("backup.sh", tmp_path, fake_docker)
    assert result.returncode == 0, result.stderr
    files = list((tmp_path / "backups").glob("*.sql.gz"))
    assert len(files) == 1 and files[0].stat().st_mode & 0o777 == 0o600
    assert b"CREATE TABLE mock" in gzip.open(files[0], "rb").read()
    assert not list((tmp_path / "backups").glob(".shopbot_*"))

    fake_docker["MOCK_FAIL_DUMP"] = "1"
    failed = _run("backup.sh", tmp_path, fake_docker)
    assert failed.returncode != 0
    assert list((tmp_path / "backups").glob("*.sql.gz")) == files
    assert not list((tmp_path / "backups").glob(".shopbot_*"))


def test_restore_rejects_corrupt_or_cancel_and_checks_psql_failure(tmp_path, fake_docker):
    bad = tmp_path / "bad.sql.gz"
    bad.write_bytes(b"not gzip")
    fake_docker["ALLOW_NONINTERACTIVE_RESTORE"] = "true"  # faqat test uchun
    refused = _run("restore.sh", tmp_path, fake_docker, str(bad), input="ha\nshopbot\n")
    assert refused.returncode != 0 and "buzilgan" in refused.stderr
    assert not Path(fake_docker["MOCK_DOCKER_LOG"]).exists()  # DB'ga tegilmadi

    backup = _run("backup.sh", tmp_path, fake_docker)
    assert backup.returncode == 0, backup.stderr
    path = next((tmp_path / "backups").glob("*.sql.gz"))
    log = Path(fake_docker["MOCK_DOCKER_LOG"])
    before = log.read_text()
    cancelled = _run("restore.sh", tmp_path, fake_docker, str(path), input="yo'q\n")
    assert cancelled.returncode == 0 and "Bekor qilindi" in cancelled.stdout
    assert log.read_text().count("psql") == before.count("psql")
    wrong_db = _run("restore.sh", tmp_path, fake_docker, str(path), input="ha\nother\n")
    assert wrong_db.returncode == 0 and "Bekor qilindi" in wrong_db.stdout
    assert "psql" not in log.read_text()

    fake_docker["MOCK_FAIL_PSQL"] = "1"
    failed = _run("restore.sh", tmp_path, fake_docker, str(path), input="ha\nshopbot\n")
    assert failed.returncode != 0 and "✅ Tiklandi" not in failed.stdout
    assert "--single-transaction" in log.read_text()
    assert "CREATE TABLE mock" in Path(fake_docker["MOCK_RESTORE_OUTPUT"]).read_text()
    fake_docker.pop("MOCK_FAIL_PSQL")
    success = _run("restore.sh", tmp_path, fake_docker, str(path), input="ha\nshopbot\n")
    assert success.returncode == 0 and "✅ Tiklandi" in success.stdout


def test_restore_refuses_when_bot_or_poster_runs(tmp_path, fake_docker):
    assert _run("backup.sh", tmp_path, fake_docker).returncode == 0
    path = next((tmp_path / "backups").glob("*.sql.gz"))
    fake_docker.update({
        "ALLOW_NONINTERACTIVE_RESTORE": "true", "MOCK_WORKERS_RUNNING": "1",
    })
    refused = _run("restore.sh", tmp_path, fake_docker, str(path), input="ha\nshopbot\n")
    assert refused.returncode != 0 and "shopbot-bot ishlab turibdi" in refused.stderr
    assert "psql" not in Path(fake_docker["MOCK_DOCKER_LOG"]).read_text()


def test_backup_rejects_bad_retention_before_pg_dump(tmp_path, fake_docker):
    fake_docker["BACKUP_RETENTION_DAYS"] = "400"
    result = _run("backup.sh", tmp_path, fake_docker)
    assert result.returncode != 0 and "BACKUP_RETENTION_DAYS" in result.stderr
    assert not Path(fake_docker["MOCK_DOCKER_LOG"]).exists()
    fake_docker["BACKUP_RETENTION_DAYS"] = "08"  # Bash octal sifatida talqin qilmasin
    assert _run("backup.sh", tmp_path, fake_docker).returncode == 0


def test_deploy_backup_never_falls_back_to_another_local_db(tmp_path, fake_docker):
    local_dump = tmp_path / "bin" / "pg_dump"
    local_dump.write_text("#!/bin/sh\nprintf 'WRONG_DB\\n'\n")
    local_dump.chmod(0o755)
    fake_docker.update({"BACKUP_REQUIRE_DOCKER": "true", "MOCK_NO_CONTAINER": "1"})
    refused = _run("backup.sh", tmp_path, fake_docker)
    assert refused.returncode != 0 and "lokal DB'dan backup olinmadi" in refused.stderr
    assert not list((tmp_path / "backups").iterdir())  # qisman nusxa ham qolmaydi


def test_deploy_check_only_never_starts_services(tmp_path, fake_docker, good_env):
    root = tmp_path / "copy"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "deploy.sh", scripts)
    shutil.copy(ROOT / "scripts" / "preflight.py", scripts)
    (root / ".env").write_text("\n".join(f"{k}={v}" for k, v in good_env.items()) + "\n")
    run = subprocess.run(["bash", str(scripts / "deploy.sh"), "--check"],
                         cwd=tmp_path, env=fake_docker, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "jonli servislar" in run.stdout or "ulanishini sinamadi" in run.stdout
    log = Path(fake_docker["MOCK_DOCKER_LOG"]).read_text()
    assert "compose version" in log and "config --quiet" in log
    assert " up " not in log and " build " not in log and " stop " not in log


def test_deploy_operator_order_with_mock_compose_only(tmp_path, fake_docker, good_env):
    """Terminal va Docker soxta: backup migratsiyadan oldin, Caddy pollingda o'chiq."""
    root = tmp_path / "deploy_copy"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for name in ("deploy.sh", "preflight.py"):
        shutil.copy(ROOT / "scripts" / name, scripts)
    (root / ".env").write_text("\n".join(f"{k}={v}" for k, v in good_env.items()) + "\n")
    (scripts / "backup.sh").write_text(
        '#!/usr/bin/env bash\necho backup >> "$MOCK_DOCKER_LOG"\n'
    )
    (scripts / "backup.sh").chmod(0o755)
    # CI foydalanuvchisi UID 1001 emas; faqat stat chaqiruvini soxtalashtiramiz.
    stat = tmp_path / "bin" / "stat"
    stat.write_text("#!/bin/sh\nprintf '1001\\n'\n")
    stat.chmod(0o755)
    master, slave = pty.openpty()
    try:
        process = subprocess.Popen(
            ["bash", str(scripts / "deploy.sh")], cwd=tmp_path,
            env=fake_docker, stdin=slave, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        os.close(slave)
        os.write(master, b"DEPLOY\n")
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, out + err
    finally:
        os.close(master)
    log = Path(fake_docker["MOCK_DOCKER_LOG"]).read_text().splitlines()
    def index(fragment):
        return next(i for i, row in enumerate(log) if fragment in row)
    assert index(" up -d --wait postgres redis") < index(" build bot poster migrate")
    assert index(" stop bot poster") < index("backup") < index(" run --rm migrate")
    assert index(" run --rm migrate") < index(" up -d --no-build bot poster")
    assert index(" up -d --no-build bot poster") < index(" stop caddy")

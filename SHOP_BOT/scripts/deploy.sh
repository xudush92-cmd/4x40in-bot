#!/usr/bin/env bash
# SHOP-BOT Compose deploy: tekshiruv → build → to'xtatish → backup → migrate → start.
# Ishlab chiqarish serverida operator bilan ishlatilsin; bu CI/zero-downtime deploy emas.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "${1:-}" != "" && "${1:-}" != "--check" ]]; then
  echo "Foydalanish: $0 [--check]" >&2
  exit 2
fi
if [[ ! -f .env ]]; then
  echo "❌ .env topilmadi. .env.example dan oling va maxfiy qiymatlarni kiriting." >&2
  exit 2
fi
python3 -m scripts.preflight --env .env
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "❌ Docker Compose v2 talab qilinadi." >&2
  exit 3
fi
docker compose --env-file .env config --quiet
if [[ "${1:-}" == "--check" ]]; then
  echo "✅ Compose konfiguratsiyasi yaroqli. Bu DB/Redis/TLS/Telegram ulanishini sinamadi."
  exit 0
fi
if [[ ! -t 0 ]]; then
  echo "❌ Deploy uchun operatorning interaktiv terminali kerak." >&2
  exit 4
fi

# Image ichidagi non-root 'shopbot' UID 1001 /app/logs katalogiga yozishi kerak.
mkdir -p logs backups
if [[ "$(stat -c '%u' logs)" != "1001" ]]; then
  echo "❌ ./logs egasi UID 1001 bo'lishi kerak (sudo chown -R 1001:1001 logs)." >&2
  exit 5
fi
read -r -p "Build, bot/posterni to'xtatish va DB migratsiyasiga rozimisiz? DEPLOY yozing: " CONFIRM
if [[ "$CONFIRM" != "DEPLOY" ]]; then
  echo "Bekor qilindi."
  exit 0
fi

# DB va Redis sog'lom bo'lmaguncha migratsiyaga o'tilmaydi.
docker compose --env-file .env up -d --wait postgres redis
docker compose --env-file .env build bot poster migrate
docker compose --env-file .env stop bot poster
# Zaxira xato bo'lsa migratsiya boshlanmaydi (bot/posterni qo'lda qayta yoqing).
BACKUP_REQUIRE_DOCKER=true ./scripts/backup.sh
docker compose --env-file .env run --rm migrate
docker compose --env-file .env up -d --no-build bot poster

WEBHOOK_MODE="$(python3 - <<'PY'
from pathlib import Path
from scripts.preflight import read_env
print(read_env(Path('.env'))['USE_WEBHOOK'])
PY
)"
if [[ "$WEBHOOK_MODE" == "true" ]]; then
  docker compose --env-file .env up -d caddy
else
  docker compose --env-file .env stop caddy
fi

docker compose --env-file .env ps
echo "✅ Deploy buyruqlari tugadi. /health, /stats, Telegram webhook va loglarni qo'lda tekshiring."

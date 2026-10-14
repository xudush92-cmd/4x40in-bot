#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Zaxira nusxadan tiklash (REJA.md 13-bo'lim)
#  Ishlatish:  ./scripts/restore.sh backups/shopbot_2026-10-15_03-00-00.sql.gz
#  DIQQAT: mavjud baza TO'LIQ almashtiriladi!
# ─────────────────────────────────────────────────────────────
set -euo pipefail

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "❌ Foydalanish: $0 <zaxira fayli.sql.gz>"
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

CONTAINER="${POSTGRES_CONTAINER:-shopbot-postgres}"
DB_USER="${POSTGRES_USER:-shopbot}"
DB_NAME="${POSTGRES_DB:-shopbot}"

read -r -p "⚠️  '${DB_NAME}' bazasi almashtiriladi. Davom etamizmi? (ha/yo'q): " CONFIRM
if [[ "$CONFIRM" != "ha" ]]; then
  echo "Bekor qilindi."
  exit 0
fi

echo "[$(date '+%F %T')] Tiklanmoqda: ${FILE}"
gunzip -c "$FILE" | docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1
echo "[$(date '+%F %T')] ✅ Tiklandi. Konteynerlarni qayta ishga tushiring: docker compose restart bot poster"

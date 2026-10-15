#!/usr/bin/env bash
# PostgreSQL zaxira nusxasi: atomar yozuv, xatoda yarim fayl qolmaydi.
# Cron: 0 3 * * * cd /opt/shopbot/SHOP_BOT && BACKUP_REQUIRE_DOCKER=true ./scripts/backup.sh >> logs/backup.log 2>&1
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
CONTAINER="${POSTGRES_CONTAINER:-shopbot-postgres}"
DB_USER="${POSTGRES_USER:-shopbot}"
DB_NAME="${POSTGRES_DB:-shopbot}"

if [[ ! "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  echo "❌ BACKUP_RETENTION_DAYS 1–365 orasida bo'lishi kerak." >&2
  exit 2
fi
RETENTION_DAYS=$((10#$RETENTION_DAYS))
if (( RETENTION_DAYS < 1 || RETENTION_DAYS > 365 )); then
  echo "❌ BACKUP_RETENTION_DAYS 1–365 orasida bo'lishi kerak." >&2
  exit 2
fi
mkdir -p -- "$BACKUP_DIR"
FILE="$BACKUP_DIR/shopbot_$(date +%Y-%m-%d_%H-%M-%S_%N).sql.gz"
TMP_FILE="$(mktemp "$BACKUP_DIR/.shopbot_XXXXXXXX.sql.gz")"
trap 'if [[ -n "${TMP_FILE:-}" ]]; then rm -f -- "$TMP_FILE"; fi' EXIT

echo "[$(date '+%F %T')] Zaxira nusxa boshlandi."
if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -Fx -- "$CONTAINER" >/dev/null; then
  docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    | gzip -9 > "$TMP_FILE"
else
  if [[ "${BACKUP_REQUIRE_DOCKER:-false}" == "true" ]]; then
    echo "❌ Deploy uchun PostgreSQL konteyneri talab qilinadi; lokal DB'dan backup olinmadi." >&2
    exit 3
  fi
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "❌ PostgreSQL konteyneri ham, lokal pg_dump ham mavjud emas." >&2
    exit 3
  fi
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump -U "$DB_USER" -h "${DB_HOST:-localhost}" \
    -d "$DB_NAME" --clean --if-exists | gzip -9 > "$TMP_FILE"
fi

# pg_dump xato bersa pipefail yuqorida uzadi, trap yarim faylni o'chiradi.
gzip -t -- "$TMP_FILE"
if [[ ! -s "$TMP_FILE" ]] || [[ "$(gzip -cd -- "$TMP_FILE" | wc -c)" -eq 0 ]]; then
  echo "❌ Bo'sh yoki buzilgan zaxira nusxasi." >&2
  exit 4
fi
# Qattiq havola yaratish atomar va mavjud shu nomli backup'ni bosib yozmaydi.
ln -- "$TMP_FILE" "$FILE"
rm -- "$TMP_FILE"
TMP_FILE=""
chmod 600 -- "$FILE"
echo "[$(date '+%F %T')] ✅ Zaxira tayyor: $FILE ($(du -h "$FILE" | cut -f1))"

# Faqat aynan shu katalogdagi eski muvaffaqiyatli zaxiralarni o'chiramiz.
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'shopbot_*.sql.gz' \
  -mmin "+$((RETENTION_DAYS * 1440))" -print -delete | sed "s/^/[o'chirildi] /"

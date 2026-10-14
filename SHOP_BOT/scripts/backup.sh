#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  PostgreSQL zaxira nusxasi (REJA.md 13-bo'lim)
#  crontab misoli (har kuni 03:00 da):
#    0 3 * * * cd /opt/shopbot && ./scripts/backup.sh >> logs/backup.log 2>&1
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# .env dan o'qish
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
STAMP="$(date +%Y-%m-%d_%H-%M-%S)"
FILE="${BACKUP_DIR}/shopbot_${STAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%F %T')] Zaxira nusxa boshlandi: ${FILE}"

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists \
    | gzip -9 > "$FILE"
else
  # Docker tashqarisida ishlayotgan bo'lsa (lokal pg_dump)
  PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump -U "$DB_USER" -h "${DB_HOST:-localhost}" -d "$DB_NAME" \
    --clean --if-exists | gzip -9 > "$FILE"
fi

SIZE="$(du -h "$FILE" | cut -f1)"
echo "[$(date '+%F %T')] ✅ Zaxira tayyor: ${FILE} (${SIZE})"

# Eskilarini o'chirish
find "$BACKUP_DIR" -name 'shopbot_*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete \
  | sed 's/^/[o'"'"'chirildi] /'

echo "[$(date '+%F %T')] Tugadi."

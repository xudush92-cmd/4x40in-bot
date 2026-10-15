#!/usr/bin/env bash
# Eski bazani pg_dump nusxasi bilan tiklash. FAQAT bot/poster to'xtatilganda!
set -euo pipefail

FILE="${1:-}"
if [[ -z "$FILE" || ! -f "$FILE" ]]; then
  echo "❌ Foydalanish: $0 <zaxira fayli.sql.gz>" >&2
  exit 2
fi
FILE="$(realpath -- "$FILE")"  # loyiha papkasiga o'tishdan OLDIN
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

CONTAINER="${POSTGRES_CONTAINER:-shopbot-postgres}"
DB_USER="${POSTGRES_USER:-shopbot}"
DB_NAME="${POSTGRES_DB:-shopbot}"

# Yaroqsiz/yarim arxivni ochib, mavjud jadvalni DROP qilmaslik uchun.
if ! gzip -t -- "$FILE" || [[ "$(gzip -cd -- "$FILE" | wc -c)" -eq 0 ]]; then
  echo "❌ Zaxira buzilgan yoki bo'sh. Baza o'zgartirilmadi." >&2
  exit 3
fi
if ! command -v docker >/dev/null 2>&1 || ! RUNNING="$(docker ps --format '{{.Names}}')"; then
  echo "❌ Docker ishlamayapti. Baza o'zgartirilmadi." >&2
  exit 4
fi
if ! grep -Fx -- "$CONTAINER" <<< "$RUNNING" >/dev/null; then
  echo "❌ PostgreSQL konteyneri ishlamayapti. Baza o'zgartirilmadi." >&2
  exit 4
fi
# Ishlayotgan worker restore vaqtida eski/yangi sxemaga yozib yubormasin.
for WORKER in shopbot-bot shopbot-poster; do
  if grep -Fx -- "$WORKER" <<< "$RUNNING" >/dev/null; then
    echo "❌ $WORKER ishlab turibdi; avval 'docker compose stop bot poster' qiling." >&2
    exit 5
  fi
done
if [[ ! -t 0 && "${ALLOW_NONINTERACTIVE_RESTORE:-false}" != "true" ]]; then
  echo "❌ Tiklash interaktiv terminal talab qiladi (testda ALLOW_NONINTERACTIVE_RESTORE=true)." >&2
  exit 5
fi

echo "⚠️  Bot va poster to'xtatilgan bo'lishi SHART. '${DB_NAME}' bazasining joriy ma'lumotlari almashtiriladi."
read -r -p "Davom etish uchun 'ha' yozing: " CONFIRM
if [[ "$CONFIRM" != "ha" ]]; then
  echo "Bekor qilindi."
  exit 0
fi
read -r -p "Tasdiq uchun baza nomini aynan kiriting: " CONFIRM_DB
if [[ "$CONFIRM_DB" != "$DB_NAME" ]]; then
  echo "Bekor qilindi: baza nomi mos emas."
  exit 0
fi

echo "[$(date '+%F %T')] Tiklanmoqda: $FILE"
# --file ishlatilgani sabab --single-transaction butun pg_dump skriptiga
# qo'llanadi. SQL xatoda ON_ERROR_STOP=1 rollback qiladi; pipefail ham tekshiradi.
gzip -cd -- "$FILE" | docker exec -i "$CONTAINER" psql -X --single-transaction \
  -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$DB_NAME" --file=/dev/stdin
echo "[$(date '+%F %T')] ✅ Tiklandi. Avval bazani tekshiring, keyin bot/posterni ishga tushiring."

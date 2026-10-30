#!/usr/bin/env bash
# zaxira.sh — botning to'liq nusxasini oladi yoki qaytaradi.
#
# Ishlatish:
#   ./zaxira.sh                  # nusxa oladi  (xizmatni to'xtatib, keyin yoqadi)
#   ./zaxira.sh --no-stop        # xizmatni to'xtatmasdan (tez, lekin WAL bilan)
#   ./zaxira.sh --list           # mavjud nusxalar ro'yxati
#   ./zaxira.sh --restore FILE   # nusxadan tiklaydi (avval eskisini saqlaydi)
#
# Xizmat nomi: SCANNER_SERVICE (standart: scanner-bot)
# Nusxa papkasi: SCANNER_BACKUP_DIR (standart: <loyiha>/zaxira)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="${SCANNER_SERVICE:-scanner-bot}"
BACKUP_DIR="${SCANNER_BACKUP_DIR:-$APP_DIR/zaxira}"
DB_FILE="${SCANNER_DB_PATH:-$APP_DIR/scanner.db}"
STAMP="$(date +%Y%m%d-%H%M%S)"
NAME="scanner-zaxira-$STAMP.tar.gz"

info()  { printf '\033[1;34m→\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

have_service() {
    command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null \
        | grep -q "^${SERVICE}\.service"
}

usage() { sed -n '/^# zaxira.sh/,/^# Xizmat nomi/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

list_backups() {
    [ -d "$BACKUP_DIR" ] || { warn "Nusxa papkasi yo'q: $BACKUP_DIR"; return 0; }
    info "Nusxalar: $BACKUP_DIR"
    ls -1t "$BACKUP_DIR"/*.tar.gz 2>/dev/null | head -20 || warn "Hozircha nusxa yo'q"
}

restore() {
    local file="$1"
    [ -f "$file" ] || die "Fayl topilmadi: $file"
    info "Tekshirilmoqda: $file"
    tar -tzf "$file" >/dev/null || die "Arxiv buzilgan: $file"

    local was_running=0
    if have_service && systemctl is-active --quiet "$SERVICE"; then
        was_running=1
        info "Xizmat to'xtatilmoqda: $SERVICE"
        systemctl stop "$SERVICE"
    fi

    # Tiklashdan oldin hozirgi holatning nusxasi olinadi.
    if [ -f "$DB_FILE" ]; then
        local safety="$BACKUP_DIR/oldin-tiklash-$STAMP.tar.gz"
        mkdir -p "$BACKUP_DIR"
        tar -czf "$safety" -C "$(dirname "$DB_FILE")" "$(basename "$DB_FILE")" 2>/dev/null || true
        warn "Avvalgi holat saqlandi: $safety"
    fi

    info "Arxiv ochilmoqda…"
    tar -xzf "$file" -C "$APP_DIR"
    ok "Tiklandi"

    if [ "$was_running" = "1" ]; then
        info "Xizmat yoqilmoqda: $SERVICE"
        systemctl start "$SERVICE"
    fi
    ok "Tayyor. Tekshirish: journalctl -u $SERVICE -n 30 --no-pager"
}

backup() {
    local stop_service="$1"
    [ -f "$DB_FILE" ] || die "Baza topilmadi: $DB_FILE (SCANNER_DB_PATH ni tekshiring)"

    mkdir -p "$BACKUP_DIR"
    local stage
    stage="$(mktemp -d)"
    trap 'rm -rf "${stage:-}"' EXIT

    info "Nusxa tayyorlanmoqda → $BACKUP_DIR/$NAME"

    local was_running=0
    if [ "$stop_service" = "1" ] && have_service && systemctl is-active --quiet "$SERVICE"; then
        was_running=1
        info "Xizmat to'xtatilmoqda: $SERVICE (baza butun nusxalansin)"
        systemctl stop "$SERVICE"
        sleep 1
    fi

    # 1) Baza (WAL fayllari bilan — aks holda oxirgi yozuvlar yo'qoladi)
    cp -a "$DB_FILE" "$stage/" 2>/dev/null || die "Bazani nusxalab bo'lmadi"
    for suffix in -wal -shm; do
        [ -f "$DB_FILE$suffix" ] && cp -a "$DB_FILE$suffix" "$stage/" || true
    done

    # 2) Sozlamalar (tokenlar) — faqat mavjud bo'lsa
    for f in .env .env.local; do
        [ -f "$APP_DIR/$f" ] && cp -a "$APP_DIR/$f" "$stage/" || true
    done

    # 3) Kalit so'zlar — o'qiladigan matn ko'rinishida (bazadan mustaqil zaxira)
    if python3 - "$APP_DIR" "$stage" <<'PY' 2>/dev/null
import sys, pathlib
app, stage = sys.argv[1], pathlib.Path(sys.argv[2])
sys.path.insert(0, app)
import database as db
db.init_db()
text = db.export_phrases_text()
(stage / "kalit-sozlar.txt").write_text(text + "\n", encoding="utf-8")
PY
    then
        ok "Kalit so'zlar ham matn sifatida saqlandi"
    else
        warn "Kalit so'zlarni matnga chiqarib bo'lmadi (baza nusxasi baribir bor)"
    fi

    # 4) Kichik ma'lumot fayli
    {
        echo "sana: $(date -Is)"
        echo "loyiha: $APP_DIR"
        echo "baza: $DB_FILE"
        echo "xizmat: $SERVICE"
        echo "git: $(git -C "$APP_DIR" log --oneline -1 2>/dev/null || echo '—')"
        echo
        echo "Tiklash: ./zaxira.sh --restore $(pwd)/$NAME"
    } > "$stage/README.txt"

    tar -czf "$BACKUP_DIR/$NAME" -C "$stage" .
    chmod 600 "$BACKUP_DIR/$NAME"

    if [ "$was_running" = "1" ]; then
        info "Xizmat yoqilmoqda: $SERVICE"
        systemctl start "$SERVICE"
    fi

    local size
    size="$(du -h "$BACKUP_DIR/$NAME" | cut -f1)"
    ok "Nusxa tayyor: $BACKUP_DIR/$NAME ($size)"
    echo
    info "Ichida:"
    tar -tzf "$BACKUP_DIR/$NAME" | sed 's|^\./|  |' | head -12
}

case "${1:-}" in
    --help|-h) usage ;;
    --list)    list_backups ;;
    --restore) [ -n "${2:-}" ] || die "--restore uchun fayl kerak: ./zaxira.sh --restore FILE"
               restore "$2" ;;
    --no-stop) backup 0 ;;
    "")        backup 1 ;;
    *)         die "Noma'lum parametr: $1 (yordam: ./zaxira.sh --help)" ;;
esac

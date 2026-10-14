# ─────────────────────────────────────────────────────────────
#  SHOP-BOT — Docker image (Python 3.12 slim)
# ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Tashkent \
    PYTHONPATH=/app

WORKDIR /app

# Tizim paketlari (tzdata — vaqt zonasi uchun zarur)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

# Avval faqat kutubxonalar (Docker kesh samarasi uchun)
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Keyin loyiha kodi
COPY . .

# Root bo'lmagan foydalanuvchi (xavfsizlik)
RUN useradd -m -u 1001 shopbot \
    && mkdir -p /app/logs /app/data \
    && chown -R shopbot:shopbot /app
USER shopbot

EXPOSE 8080

# /health orqali konteyner salomatligini tekshirish
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

# Standart buyruq (docker-compose da almashtiriladi: bot / poster)
CMD ["python", "-m", "app.main"]

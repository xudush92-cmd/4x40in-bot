"""
health.py — Health check va monitoring.

HTTP endpoint /health — UptimeRobot, AWS CloudWatch yoki
boshqa monitoring xizmatlari uchun.

Afzalliklari:
- Bot tirikligini tashqaridan tekshirish
- RAM, CPU, uptime statistikasi
- Worker va client pool holati
- Admin uchun /status buyruqida to'liq ma'lumot
- /stats endpoint optional token bilan himoyalangan
"""

from __future__ import annotations

import os
import platform
import resource
import time
from aiohttp import web

# ─────────────────────────────────────────────────────────────────────────
# KONFIGURATSIYA
# ─────────────────────────────────────────────────────────────────────────
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))
HEALTH_HOST = os.getenv("HEALTH_HOST", "0.0.0.0")
# Agar HEALTH_TOKEN qo'yilgan bo'lsa, /stats endpoint shu token talab qiladi.
# Bo'sh bo'lsa, faqat localhost'dan kirish ruxsat etiladi (default).
HEALTH_TOKEN = os.getenv("HEALTH_TOKEN", "").strip()

START_TIME = time.time()


class HealthServer:
    """Yengil HTTP server — monitoring uchun."""

    def __init__(self):
        self._app = web.Application()
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_get("/stats", self._handle_stats)
        self._runner: web.AppRunner | None = None
        self._worker_stats_fn = None
        self._pool_stats_fn = None

    def set_stats_providers(
        self,
        worker_stats_fn=None,
        pool_stats_fn=None,
    ) -> None:
        """Worker va pool statistika funksiyalarini sozlash."""
        self._worker_stats_fn = worker_stats_fn
        self._pool_stats_fn = pool_stats_fn

    async def start(self) -> None:
        """HTTP serverni ishga tushirish."""
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, HEALTH_HOST, HEALTH_PORT)
        await site.start()

    async def stop(self) -> None:
        """HTTP serverni to'xtatish."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health — oddiy tiriklik tekshiruvi (har kim ko'ra oladi)."""
        uptime = int(time.time() - START_TIME)
        data = {
            "status": "ok",
            "uptime_seconds": uptime,
            "uptime_human": _format_uptime(uptime),
        }
        return web.json_response(data)

    async def _handle_stats(self, request: web.Request) -> web.Response:
        """
        GET /stats — to'liq statistika.

        Xavfsizlik:
        - HEALTH_TOKEN qo'yilgan bo'lsa: ?token=... yoki Authorization header
          orqali tekshiriladi.
        - Token qo'yilmagan bo'lsa: faqat localhost (127.0.0.1, ::1)
          dan kirish ruxsat etiladi.
        """
        if not _is_authorized(request):
            return web.json_response({"error": "forbidden"}, status=403)

        uptime = int(time.time() - START_TIME)
        data = {
            "status": "ok",
            "uptime_seconds": uptime,
            "uptime_human": _format_uptime(uptime),
            "memory": _get_memory_info(),
        }

        if self._worker_stats_fn:
            try:
                data["workers"] = self._worker_stats_fn()
            except Exception as e:
                data["workers_error"] = f"{type(e).__name__}: {e}"

        if self._pool_stats_fn:
            try:
                data["client_pool"] = self._pool_stats_fn()
            except Exception as e:
                data["client_pool_error"] = f"{type(e).__name__}: {e}"

        return web.json_response(data)


def _is_authorized(request: web.Request) -> bool:
    """Token tekshiruvi yoki localhost-only."""
    if HEALTH_TOKEN:
        # Authorization: Bearer <token>
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and auth[len("Bearer "):] == HEALTH_TOKEN:
            return True
        # ?token=... query string
        token = request.query.get("token", "")
        if token == HEALTH_TOKEN:
            return True
        return False
    # Token yo'q — faqat localhost
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if not peer:
        return False
    host = peer[0] if isinstance(peer, tuple) else None
    return host in ("127.0.0.1", "::1", "localhost")


def _format_uptime(seconds: int) -> str:
    """Soniyalarni inson o'qiydigan formatga."""
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _get_memory_info() -> dict:
    """Joriy jarayon RAM iste'moli (Linux/Mac)."""
    # Birinchi: resource module (Linux/Mac)
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss = usage.ru_maxrss  # Linux: KB, Mac: bytes
        if platform.system() == "Darwin":
            rss_mb = rss / (1024 * 1024)
        else:
            rss_mb = rss / 1024
        return {"rss_mb": round(rss_mb, 1)}
    except Exception:
        pass

    # Ikkinchi: /proc/self/status (Linux)
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return {"rss_mb": round(kb / 1024, 1)}
    except Exception:
        pass

    return {"rss_mb": None}


def format_status_message(
    uptime_s: int,
    worker_stats: dict | None = None,
    pool_stats: dict | None = None,
    memory: dict | None = None,
) -> str:
    """Admin uchun /status xabarida ko'rsatiladigan tizim holati."""
    lines = [
        "🖥 TIZIM HOLATI",
        f"⏱ Uptime: {_format_uptime(uptime_s)}",
    ]

    if memory and memory.get("rss_mb"):
        lines.append(f"💾 RAM: {memory['rss_mb']} MB")

    if worker_stats:
        lines.append(
            f"👷 Workerlar: {worker_stats['active']}/{worker_stats['max']}"
        )

    if pool_stats:
        lines.append(
            f"🔌 Clientlar: {pool_stats['active']} faol, "
            f"{pool_stats['idle']} idle / {pool_stats['max']} max"
        )

    return "\n".join(lines)

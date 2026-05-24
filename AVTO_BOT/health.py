"""
health.py — Health check va monitoring.

HTTP endpoint /health — UptimeRobot, AWS CloudWatch yoki
boshqa monitoring xizmatlari uchun.

Afzalliklari:
- Bot tirikligini tashqaridan tekshirish
- RAM, CPU, uptime statistikasi
- Worker va client pool holati
- Admin uchun /status buyruqida to'liq ma'lumot
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from aiohttp import web

# ─────────────────────────────────────────────────────────────────────────
# KONFIGURATSIYA
# ─────────────────────────────────────────────────────────────────────────
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))
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
        site = web.TCPSite(self._runner, "0.0.0.0", HEALTH_PORT)
        await site.start()

    async def stop(self) -> None:
        """HTTP serverni to'xtatish."""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    async def _handle_health(self, request: web.Request) -> web.Response:
        """GET /health — oddiy tiriklik tekshiruvi."""
        uptime = int(time.time() - START_TIME)
        data = {
            "status": "ok",
            "uptime_seconds": uptime,
            "uptime_human": _format_uptime(uptime),
        }
        return web.json_response(data)

    async def _handle_stats(self, request: web.Request) -> web.Response:
        """GET /stats — to'liq statistika (himoyalangan)."""
        uptime = int(time.time() - START_TIME)

        data = {
            "status": "ok",
            "uptime_seconds": uptime,
            "uptime_human": _format_uptime(uptime),
            "memory": _get_memory_info(),
        }

        if self._worker_stats_fn:
            data["workers"] = self._worker_stats_fn()

        if self._pool_stats_fn:
            data["client_pool"] = self._pool_stats_fn()

        return web.json_response(data)


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
    try:
        import resource
        # ru_maxrss: KB (Linux) yoki bytes (Mac)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        rss_kb = usage.ru_maxrss
        # Linux'da KB, Mac'da bytes
        import platform
        if platform.system() == "Darwin":
            rss_mb = rss_kb / (1024 * 1024)
        else:
            rss_mb = rss_kb / 1024
        return {"rss_mb": round(rss_mb, 1)}
    except Exception:
        pass

    # /proc/self/status dan o'qish (Linux)
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

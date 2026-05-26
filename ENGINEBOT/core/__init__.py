"""ENGINEBOT yadrosi (core) — barcha asosiy infratuzilma modullari.

Bu paketda quyidagi modullar:
- database         : SQLite + per-tenant izolyatsiya
- tenant_manager   : tenant boshqaruvi va billing
- permissions      : 4 darajali ruxsat tizimi
- event_bus        : pluginlar uchun event tizimi
- audit_log        : har bir amal yoziladi
- rate_limiter     : anti-spam himoya
- notifier         : bildirishnoma va ogohlantirish
- error_handler    : crash isolation
"""

"""
keyboards/super_admin_kb.py — super admin (siz) menyusi.
"""

from __future__ import annotations

from keyboards.common_kb import Btn, inline_grid, make_reply


def super_admin_main_menu():
    """
    Super admin asosiy menyusi.

    👥 Tenantlar         📊 Global statistika
    📜 Muddat tarixi     📨 Broadcast
    📜 Global log        🛠 Tizim
    ℹ️ Yordam
    """
    return make_reply([
        [Btn.ALL_TENANTS, Btn.GLOBAL_STATS],
        [Btn.PAYMENTS, Btn.BROADCAST],
        [Btn.GLOBAL_AUDIT, Btn.SYSTEM],
        [Btn.HELP],
    ])


# ─────────────────────────────────────────────────────────────────────
# Tenantlar boshqaruvi
# ─────────────────────────────────────────────────────────────────────
def tenants_filter():
    """Tenantlar filtri."""
    items = [
        ("👥 Hammasi", "super:tenants:filter:all"),
        ("🟢 Aktiv", "super:tenants:filter:active"),
        ("🟡 Kutilayotgan", "super:tenants:filter:pending"),
        ("⏸ Pause", "super:tenants:filter:paused"),
        ("🔴 Bloklangan", "super:tenants:filter:blocked"),
    ]
    return inline_grid(
        items,
        columns=2,
        extra_rows=[[(Btn.BACK, "super:tenants:back")]],
    )


def tenant_actions(tenant_id: int, status: str = "active"):
    """Bitta tenant ustida amallar (PULSIZ model)."""
    items: list[tuple[str, str]] = [
        ("📊 Statistika", f"super:tenant:stats:{tenant_id}"),
        ("👥 Foydalanuvchilar", f"super:tenant:users:{tenant_id}"),
        ("📜 Muddat tarixi", f"super:tenant:payments:{tenant_id}"),
        ("📜 Audit log", f"super:tenant:audit:{tenant_id}"),
        ("📨 Xabar yuborish", f"super:tenant:message:{tenant_id}"),
    ]
    items.append(("📅 Tarif/muddat belgilash", f"super:tenant:extend:{tenant_id}"))

    if status == "pending":
        items.insert(0, ("✅ Tasdiqlash", f"super:tenant:approve:{tenant_id}"))

    if status == "active":
        items.append(("⏸ Pause", f"super:tenant:pause:{tenant_id}"))
        items.append(("⛔ Bloklash", f"super:tenant:block:{tenant_id}"))

    if status in ("paused", "blocked"):
        items.append(("✅ Tiklash", f"super:tenant:unblock:{tenant_id}"))

    items.append(("🗑 Oʻchirish", f"super:tenant:delete:{tenant_id}"))

    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "super:tenants:list")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Tarif tanlash (to'lov qabul qilish uchun)
# ─────────────────────────────────────────────────────────────────────
def tariff_picker(tenant_id: int):
    """
    Tarif tanlash — PULSIZ model.

    Har tarif faqat cheklovlar bilan farqlanadi (kanal soni, user soni).
    Pul kiritilmaydi — super admin og'zaki kelishuv asosida tarif beradi.
    """
    items = [
        ("🆓 Trial (sinov muddati)", f"super:payment:tariff:{tenant_id}:trial"),
        ("🥉 Bronze (kichik guruh)", f"super:payment:tariff:{tenant_id}:bronze"),
        ("🥈 Silver (o'rta guruh)", f"super:payment:tariff:{tenant_id}:silver"),
        ("🥇 Gold (katta guruh)", f"super:payment:tariff:{tenant_id}:gold"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, f"super:tenant:show:{tenant_id}")]],
    )


# ─────────────────────────────────────────────────────────────────────
# Pending tenant tasdiqlash (notification ostida)
# ─────────────────────────────────────────────────────────────────────
def approve_tenant_inline(tenant_id: int):
    """Yangi tenant tasdiqlash inline tugmalari (PULSIZ model).

    Trial — eng tezkor (default 7 kun).
    Tarif berish — muddat tanlash bilan (og'zaki kelishuv).
    """
    return inline_grid(
        [
            ("✅ Trial bilan aktivlashtirish", f"super:tenant:approve_trial:{tenant_id}"),
            ("📦 Tarif belgilash", f"super:tenant:add_payment:{tenant_id}"),
            ("❌ Rad etish", f"super:tenant:reject:{tenant_id}"),
        ],
        columns=1,
    )


# ─────────────────────────────────────────────────────────────────────
# Tizim
# ─────────────────────────────────────────────────────────────────────
def system_menu():
    """Tizim panel (RAM, log, backup va h.k.)."""
    items = [
        ("📊 Holat", "super:system:status"),
        ("💾 Backup yaratish", "super:system:backup"),
        ("🧹 Eski loglarni tozalash", "super:system:cleanup_logs"),
        ("🔄 Servislarni qayta yuklash", "super:system:restart_services"),
    ]
    return inline_grid(
        items,
        columns=1,
        extra_rows=[[(Btn.BACK, "super:menu")]],
    )

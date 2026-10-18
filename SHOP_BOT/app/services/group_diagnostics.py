"""Guruh qoidalarini o'zgartirmaydigan holat diagnostikasi (UX-1)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CleanerSetting, CounterSetting, Group, GuardSetting, Setting
from app.services import counter_service, group_policy_service
from app.services.settings_service import DEFAULTS
from app.utils.text import escape_html
from app.utils.time import fmt_dt

_GLOBAL_KEYS = ("kill_switch", "maintenance_mode", "posting_enabled_global",
                "counter_enabled_global", "guard_enabled_global", "cleaner_enabled_global")


def _rule(label: str, *, global_on: bool, group_on: bool, policy_on: bool,
          dry_run: bool, rights_ok: bool, base_ok: bool) -> str:
    if not global_on:
        state = "🔴 global pauza"
    elif not base_ok:
        state = "🔴 guruh pauzada yoki superguruh/bot admin emas"
    elif not group_on:
        state = "🔴 shu guruh switchi o'chiq"
    elif not policy_on:
        state = "🔴 qoida o'chiq"
    elif dry_run:
        state = "🧪 sinovda (jonli amal yo'q)"
    elif not rights_ok:
        state = "⚠️ kerakli bot huquqi tasdiqlanmagan"
    else:
        state = "🔴 JONLI (Telegram a'zoligi/huquqlari amalda yana tekshiriladi)"
    return f"{label}: {state}"


async def diagnostic_text(session: AsyncSession, group: Group) -> str:
    """Global → guruh → qoida → sinov/jonli → huquq; faqat o'qish."""
    rows = (await session.execute(select(Setting.key, Setting.value).where(Setting.key.in_(_GLOBAL_KEYS)))).all()
    flags = {key: DEFAULTS.get(key) for key in _GLOBAL_KEYS}
    flags.update(dict(rows))
    base = not (flags["kill_switch"] or flags["maintenance_mode"])
    group_ready = bool(group.is_active and group.is_supergroup and group.bot_is_admin)
    setting = group.settings
    rights = group.bot_rights or {}
    can_delete = bool(group.bot_is_admin and rights.get("can_delete_messages"))
    can_restrict = bool(group.bot_is_admin and rights.get("can_restrict_members"))
    guard = await session.get(GuardSetting, group.id) or group_policy_service.safe_guard(group.id)
    cleaner = await session.get(CleanerSetting, group.id) or group_policy_service.safe_cleaner(group.id)
    counter = await session.get(CounterSetting, group.id) or counter_service.safe_counter(group.id)

    lines = [
        f"🔍 <b>{escape_html(group.display)} — nega ishlamayapti?</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Global: {'🔴 favqulodda pauza' if flags['kill_switch'] else '🟢'} · "
        f"Texnik: {'🔴 yoqilgan' if flags['maintenance_mode'] else '🟢 o‘chiq'}",
        f"Guruh: {'🟢 faol' if group.is_active else '🔴 pauzada'} · "
        f"Bot: {'✅ admin' if group.bot_is_admin else '⚠️ admin emas/tekshirilmagan'} · "
        f"{'superguruh' if group.is_supergroup else '⚠️ superguruh emas'}",
        f"Bot huquqlari (so‘nggi tekshiruv): o‘chirish {'✅' if can_delete else '⚠️'}, "
        f"cheklash {'✅' if can_restrict else '⚠️'} (HARD uchun)",
        f"Oxirgi tekshiruv: {fmt_dt(group.last_checked_at) if group.last_checked_at else 'yo‘q; 🔄 qayta tekshiring'}",
        "",
        _rule("📢 Joylash", global_on=bool(base and flags["posting_enabled_global"]),
              group_on=bool(setting and setting.posting_enabled), policy_on=True, dry_run=False,
              rights_ok=group.bot_is_admin, base_ok=group_ready),
        _rule("🛡 Posbon", global_on=bool(base and flags["guard_enabled_global"]),
              group_on=bool(setting and setting.guard_enabled), policy_on=guard.enabled,
              dry_run=guard.dry_run, rights_ok=can_delete and (guard.penalty == "warn" or can_restrict),
              base_ok=group_ready),
        _rule("🧹 Tozalovchi", global_on=bool(base and flags["cleaner_enabled_global"]),
              group_on=bool(setting and setting.cleaner_enabled), policy_on=cleaner.enabled,
              dry_run=cleaner.dry_run, rights_ok=can_delete, base_ok=group_ready),
        _rule("🧮 Sanoqchi", global_on=bool(base and flags["counter_enabled_global"]),
              group_on=bool(setting and setting.counter_enabled), policy_on=counter.enabled,
              dry_run=counter.dry_run,
              rights_ok=can_delete and (counter.mode != "hard" or can_restrict),
              base_ok=group_ready),
        f"  ↳ N={counter.required_n} · bevosita qo'shish "
        f"{'yoqilgan' if (counter.count_sources or {}).get('added_by') else 'o‘chiq'}",
    ]
    lines.append("<i>Bu ekran sozlamalarni o'zgartirmaydi. Telegram Privacy Mode va "
                 "jonli huquqlarni alohida tekshiring.</i>")
    return "\n".join(lines)

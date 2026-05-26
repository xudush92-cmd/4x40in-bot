"""
core/permissions.py — 4 darajali ruxsat tizimi (V1 redesign).

ROLLAR (asosiy):
────────────────
1. SUPER_ADMIN  — bot egasi (siz). Hammasini koʻradi va boshqaradi.
2. TENANT       — kanal egasi. Faqat oʻz guruhini boshqaradi.
3. MODERATOR    — tenant tomonidan tayinlangan yordamchi (v1.5+ uchun zaxira).
4. USER         — oddiy foydalanuvchi. Sub-rollar bor (POSTER, CUSTOMER, BOTH).
5. GUEST        — roʻyxatdan oʻtmagan (faqat /start)

USER SUB-ROLLAR (V1):
─────────────────────
- POSTER   — eʼlon beruvchi (taksist, usta, ishchi)
- CUSTOMER — mijoz (qidiruvchi)
- BOTH     — ikkala rolda (taksist mijoz ham)

PRINSIPLAR:
───────────
- ROL ANIQLASH (resolve_role): user_id va tenant_id boʻyicha aniq rol
  qaytaradi. Bitta foydalanuvchi har xil tenantda har xil rolda boʻladi.

- RUXSAT TEKSHIRISH (can): rol va action boʻyicha True/False qaytaradi.
  Hech qachon "default allow" yoʻq — fail-closed.

- SUB-ROL: USER ichida POSTER/CUSTOMER/BOTH (ctx.user_sub_role).
  Posterga e'lon yozish ruxsati, customer'ga qidiruv ruxsati.

- IZOLYATSIYA: tenant boshqa tenantning maʼlumotini koʻra olmaydi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from config import Role, SUPER_ADMIN_ID, UserRole
from core import database as db

logger = logging.getLogger("enginebot.permissions")


# ─────────────────────────────────────────────────────────────────────
# Action — ruxsat sʼaratoqlari
# ─────────────────────────────────────────────────────────────────────
class Action(str, Enum):
    """Tizimdagi barcha amallar (rolga qarab ruxsat etiladi)."""

    # ─── Super Admin global amallar ─────────────────────────────────
    VIEW_ALL_TENANTS = "view_all_tenants"
    CREATE_TENANT = "create_tenant"
    BLOCK_TENANT = "block_tenant"
    DELETE_TENANT = "delete_tenant"
    EXTEND_TENANT_PAYMENT = "extend_tenant_payment"
    VIEW_GLOBAL_STATS = "view_global_stats"
    VIEW_GLOBAL_AUDIT = "view_global_audit"
    BROADCAST_MESSAGE = "broadcast_message"
    MANAGE_SYSTEM = "manage_system"

    # ─── Tenant amallar (oʻz guruhi ichida) ─────────────────────────
    CONNECT_CHANNEL = "connect_channel"
    DISCONNECT_CHANNEL = "disconnect_channel"
    SET_MIN_ROTATION = "set_min_rotation"     # tenant min interval cheklovi
    TOGGLE_BOT = "toggle_bot"
    TOGGLE_POST_INTAKE = "toggle_post_intake"
    APPROVE_USER = "approve_user"
    BLOCK_USER = "block_user"
    DELETE_USER = "delete_user"
    APPOINT_MODERATOR = "appoint_moderator"
    REMOVE_MODERATOR = "remove_moderator"
    VIEW_TENANT_STATS = "view_tenant_stats"
    VIEW_TENANT_AUDIT = "view_tenant_audit"
    DELETE_ANY_POST = "delete_any_post"
    PAUSE_ANY_POST = "pause_any_post"
    SET_AUTO_APPROVAL = "set_auto_approval"   # tenant auto/manual approve

    # ─── Moderator amallar (cheklangan, v1.5+) ──────────────────────
    REVIEW_USER_REQUESTS = "review_user_requests"
    WARN_USER = "warn_user"
    PAUSE_OTHER_POST = "pause_other_post"
    VIEW_QUEUE = "view_queue"

    # ─── User: POSTER amallari ──────────────────────────────────────
    BECOME_POSTER = "become_poster"           # guest → poster
    CREATE_OWN_POST = "create_own_post"       # erkin matn eʼlon
    EDIT_OWN_POST = "edit_own_post"
    DELETE_OWN_POST = "delete_own_post"
    VIEW_OWN_POSTS = "view_own_posts"
    TOGGLE_OWN_ROTATION = "toggle_own_rotation"  # START/STOP
    SET_OWN_INTERVAL = "set_own_interval"        # interval o'zgartirish (min 10)
    SET_OWN_CATEGORY = "set_own_category"        # soha tanlash/oʻzgartirish

    # ─── User: CUSTOMER amallari ────────────────────────────────────
    BECOME_CUSTOMER = "become_customer"       # guest → customer
    SEARCH_POSTS = "search_posts"             # filtr bilan qidirish
    BROWSE_FEED = "browse_feed"               # yangi eʼlonlar lentasi
    BOOKMARK_POST = "bookmark_post"           # saqlash (v1.5+)
    SUBSCRIBE_CATEGORY = "subscribe_category" # kuzatuv (v1.5+)
    RATE_POSTER = "rate_poster"               # baholash (v1.5+)
    CONTACT_POSTER = "contact_poster"         # bog'lanish

    # ─── User umumiy ────────────────────────────────────────────────
    EDIT_OWN_PROFILE = "edit_own_profile"
    VIEW_OWN_HISTORY = "view_own_history"
    LOGOUT = "logout"

    # ─── Hamma foydalanadigan ───────────────────────────────────────
    VIEW_HELP = "view_help"


# ─────────────────────────────────────────────────────────────────────
# Ruxsat matritsasi (rol → ruxsat berilgan amallar toʻplami)
# ─────────────────────────────────────────────────────────────────────
# Eslatma: SUPER_ADMIN avtomatik HAMMA narsani qila oladi (pastda mantiq).

# Asosiy ruxsatlar (rol bo'yicha, sub-rolga bog'liq emas)
_PERMISSIONS: dict[str, frozenset[Action]] = {
    Role.GUEST: frozenset({
        Action.VIEW_HELP,
        Action.BECOME_POSTER,
        Action.BECOME_CUSTOMER,
    }),
    Role.MODERATOR: frozenset({
        Action.VIEW_HELP,
        Action.LOGOUT,
        Action.EDIT_OWN_PROFILE,
        Action.REVIEW_USER_REQUESTS,
        Action.APPROVE_USER,
        Action.WARN_USER,
        Action.PAUSE_OTHER_POST,
        Action.VIEW_QUEUE,
    }),
    Role.TENANT: frozenset({
        Action.VIEW_HELP,
        Action.LOGOUT,
        Action.CONNECT_CHANNEL,
        Action.DISCONNECT_CHANNEL,
        Action.SET_MIN_ROTATION,
        Action.TOGGLE_BOT,
        Action.TOGGLE_POST_INTAKE,
        Action.APPROVE_USER,
        Action.BLOCK_USER,
        Action.DELETE_USER,
        Action.APPOINT_MODERATOR,
        Action.REMOVE_MODERATOR,
        Action.VIEW_TENANT_STATS,
        Action.VIEW_TENANT_AUDIT,
        Action.DELETE_ANY_POST,
        Action.PAUSE_ANY_POST,
        Action.WARN_USER,
        Action.REVIEW_USER_REQUESTS,
        Action.VIEW_QUEUE,
        Action.SET_AUTO_APPROVAL,
    }),
    # USER ruxsatlari sub-rolga qarab dynamic — pastda hisoblanadi
    Role.USER: frozenset({
        Action.VIEW_HELP,
        Action.LOGOUT,
        Action.EDIT_OWN_PROFILE,
        Action.VIEW_OWN_HISTORY,
    }),
}

# Sub-rol uchun qo'shimcha ruxsatlar
_USER_SUB_PERMISSIONS: dict[str, frozenset[Action]] = {
    UserRole.POSTER: frozenset({
        Action.CREATE_OWN_POST,
        Action.EDIT_OWN_POST,
        Action.DELETE_OWN_POST,
        Action.VIEW_OWN_POSTS,
        Action.TOGGLE_OWN_ROTATION,
        Action.SET_OWN_INTERVAL,
        Action.SET_OWN_CATEGORY,
    }),
    UserRole.CUSTOMER: frozenset({
        Action.SEARCH_POSTS,
        Action.BROWSE_FEED,
        Action.BOOKMARK_POST,
        Action.SUBSCRIBE_CATEGORY,
        Action.RATE_POSTER,
        Action.CONTACT_POSTER,
    }),
}
# BOTH = poster + customer ruxsatlari
_USER_SUB_PERMISSIONS[UserRole.BOTH] = (
    _USER_SUB_PERMISSIONS[UserRole.POSTER]
    | _USER_SUB_PERMISSIONS[UserRole.CUSTOMER]
)


# ─────────────────────────────────────────────────────────────────────
# RoleContext — bitta soʻrov uchun rol ma'lumoti
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RoleContext:
    """
    Bitta foydalanuvchi va kontekstdagi roli.

    user_id        — Telegram user ID
    role           — aniqlangan asosiy rol (Role.* dan)
    tenant_id      — qaysi tenant'da (None = global yoki tenant tanlanmagan)
    user_sub_role  — USER ichida POSTER/CUSTOMER/BOTH (boshqa rol bo'lsa None)
    """
    user_id: int
    role: str
    tenant_id: int | None = None
    user_sub_role: str | None = None  # POSTER / CUSTOMER / BOTH

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN

    @property
    def is_tenant(self) -> bool:
        return self.role == Role.TENANT

    @property
    def is_moderator(self) -> bool:
        return self.role == Role.MODERATOR

    @property
    def is_user(self) -> bool:
        return self.role == Role.USER

    @property
    def is_guest(self) -> bool:
        return self.role == Role.GUEST

    @property
    def is_poster(self) -> bool:
        """USER va sub-rol POSTER yoki BOTH bo'lsa."""
        return self.is_user and self.user_sub_role in (UserRole.POSTER, UserRole.BOTH)

    @property
    def is_customer(self) -> bool:
        """USER va sub-rol CUSTOMER yoki BOTH bo'lsa."""
        return self.is_user and self.user_sub_role in (UserRole.CUSTOMER, UserRole.BOTH)


# ─────────────────────────────────────────────────────────────────────
# Rol aniqlash
# ─────────────────────────────────────────────────────────────────────
async def resolve_role(user_id: int, tenant_id: int | None = None) -> RoleContext:
    """
    Foydalanuvchi rolini aniqlash.

    Mantiq:
      1. Telegram ID == SUPER_ADMIN_ID → SUPER_ADMIN (har joyda)
      2. tenant_id == user_id boʻlsa va u tenants jadvalida bor → TENANT
      3. moderators jadvalida (tenant_id, user_id) bor → MODERATOR
      4. users jadvalida (tenant_id, user_id) bor va status active → USER
         (sub-rol DB'dan: poster/customer/both)
      5. Aks holda → GUEST
    """
    # 1. Super admin har doim ustunlikka ega
    if user_id == SUPER_ADMIN_ID:
        return RoleContext(user_id=user_id, role=Role.SUPER_ADMIN, tenant_id=tenant_id)

    # tenant_id berilmagan boʻlsa — user oʻzi tenantmi tekshiramiz
    if tenant_id is None:
        tenant = await db.get_tenant(user_id)
        if tenant is not None:
            return RoleContext(user_id=user_id, role=Role.TENANT, tenant_id=user_id)
        return RoleContext(user_id=user_id, role=Role.GUEST, tenant_id=None)

    # 2. Tenant kontekstida — oʻzi tenantmi?
    if tenant_id == user_id:
        tenant = await db.get_tenant(user_id)
        if tenant is not None:
            return RoleContext(user_id=user_id, role=Role.TENANT, tenant_id=user_id)

    # 3. Moderator?
    if await db.is_moderator(tenant_id, user_id):
        return RoleContext(user_id=user_id, role=Role.MODERATOR, tenant_id=tenant_id)

    # 4. Oddiy user? Sub-rolni DB'dan olamiz
    user = await db.get_user(tenant_id, user_id)
    if user is not None:
        sub_role = user.get("user_role") or UserRole.CUSTOMER
        if sub_role not in UserRole.ALL:
            sub_role = UserRole.CUSTOMER
        return RoleContext(
            user_id=user_id,
            role=Role.USER,
            tenant_id=tenant_id,
            user_sub_role=sub_role,
        )

    # 5. Roʻyxatdan oʻtmagan
    return RoleContext(user_id=user_id, role=Role.GUEST, tenant_id=tenant_id)


# ─────────────────────────────────────────────────────────────────────
# Ruxsat tekshirish
# ─────────────────────────────────────────────────────────────────────
def can(ctx: RoleContext, action: Action | str) -> bool:
    """
    Foydalanuvchi shu amalni qila oladimi?

    Returns:
        True  — ruxsat berilgan
        False — ruxsat yoʻq (default fail-closed)
    """
    # Super admin — har doim ruxsat
    if ctx.role == Role.SUPER_ADMIN:
        return True

    # String yoki Action — ikkalasini ham qabul qilamiz
    if isinstance(action, str):
        try:
            action = Action(action)
        except ValueError:
            logger.warning(f"Nomaʼlum action: {action}")
            return False

    # Asosiy rol ruxsatlari
    base_allowed = _PERMISSIONS.get(ctx.role, frozenset())
    if action in base_allowed:
        return True

    # USER bo'lsa — sub-rolni ham tekshiramiz
    if ctx.role == Role.USER and ctx.user_sub_role:
        sub_allowed = _USER_SUB_PERMISSIONS.get(ctx.user_sub_role, frozenset())
        if action in sub_allowed:
            return True

    return False


def can_any(ctx: RoleContext, actions: Iterable[Action | str]) -> bool:
    """Ushbu amallarning hech boʻlmasa bittasiga ruxsat bormi?"""
    return any(can(ctx, a) for a in actions)


def can_all(ctx: RoleContext, actions: Iterable[Action | str]) -> bool:
    """Barcha amallarga ruxsat bormi?"""
    return all(can(ctx, a) for a in actions)


# ─────────────────────────────────────────────────────────────────────
# Ortiqcha xavfsizlik tekshiruvlari
# ─────────────────────────────────────────────────────────────────────
def assert_can(ctx: RoleContext, action: Action | str) -> None:
    """Ruxsatni tekshirish va xato boʻlsa raise qilish."""
    if not can(ctx, action):
        raise PermissionDenied(
            f"Foydalanuvchi {ctx.user_id} (rol: {ctx.role}, "
            f"sub: {ctx.user_sub_role}) '{action}' amalini bajara olmaydi."
        )


def assert_same_tenant(ctx: RoleContext, target_tenant_id: int) -> None:
    """
    Tenant izolyatsiyasi: faqat oʻz tenantida ishlay oladi.
    Super admin har qanday tenantga kira oladi — undan istisno.
    """
    if ctx.role == Role.SUPER_ADMIN:
        return
    if ctx.tenant_id is None or ctx.tenant_id != target_tenant_id:
        raise PermissionDenied(
            f"Cross-tenant access: user {ctx.user_id} (tenant {ctx.tenant_id}) "
            f"→ target tenant {target_tenant_id}"
        )


# ─────────────────────────────────────────────────────────────────────
# Xatoliklar
# ─────────────────────────────────────────────────────────────────────
class PermissionDenied(Exception):
    """Foydalanuvchining ushbu amalga ruxsati yoʻq."""

    def __init__(self, message: str = "Sizda bu amal uchun ruxsat yoʻq.") -> None:
        super().__init__(message)
        self.user_message = (
            "🚫 Sizda bu amal uchun ruxsat yoʻq.\n\n"
            "Agar bu xato deb hisoblasangiz, kanal egasi bilan bogʻlaning."
        )


# ─────────────────────────────────────────────────────────────────────
# Yordamchi: rol nomi (UI uchun)
# ─────────────────────────────────────────────────────────────────────
_ROLE_LABELS_UZ: dict[str, str] = {
    Role.SUPER_ADMIN: "👑 Super Admin",
    Role.TENANT: "🏢 Guruh egasi",
    Role.MODERATOR: "👮 Moderator",
    Role.USER: "👤 Foydalanuvchi",
    Role.GUEST: "🚪 Mehmon",
}

_SUB_ROLE_LABELS_UZ: dict[str, str] = {
    UserRole.POSTER: "📝 Eʼlon beruvchi",
    UserRole.CUSTOMER: "🔍 Mijoz",
    UserRole.BOTH: "🔄 Ikkalasi",
}


def role_label(role: str) -> str:
    """Rol nomini koʻrsatish uchun."""
    return _ROLE_LABELS_UZ.get(role, f"❓ {role}")


def sub_role_label(sub_role: str | None) -> str:
    """Sub-rol nomini koʻrsatish uchun."""
    if not sub_role:
        return ""
    return _SUB_ROLE_LABELS_UZ.get(sub_role, f"❓ {sub_role}")


def full_role_label(ctx: RoleContext) -> str:
    """Toʻliq ko'rinish: rol + sub-rol."""
    base = role_label(ctx.role)
    if ctx.role == Role.USER and ctx.user_sub_role:
        return f"{base} ({sub_role_label(ctx.user_sub_role)})"
    return base

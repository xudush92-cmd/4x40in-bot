"""
core/permissions.py — 4 darajali ruxsat tizimi.

ROLLAR:
───────
1. SUPER_ADMIN  — bot egasi (siz). Hammasini koʻradi va boshqaradi.
2. TENANT       — kanal egasi. Faqat oʻz guruhini boshqaradi.
3. MODERATOR    — tenant tomonidan tayinlangan yordamchi. Cheklangan.
4. USER         — oddiy foydalanuvchi. Faqat oʻzini koʻradi.
5. GUEST        — roʻyxatdan oʻtmagan (faqat /start)

PRINSIPLAR:
───────────
- ROL ANIQLASH (resolve_role): user_id va tenant_id boʻyicha aniq rol
  qaytaradi. Bitta foydalanuvchi har xil tenantda har xil rolda boʻladi:
  masalan, A tenantida SUPER_ADMIN, B tenantida TENANT, C'da USER.

- RUXSAT TEKSHIRISH (can): rol va action boʻyicha True/False qaytaradi.
  Hech qachon "default allow" yoʻq — ruxsat aniq berilgan boʻlsa True.

- IZOLYATSIYA: tenant boshqa tenantning maʼlumotini koʻra olmaydi.
  Bu DB qatlamida ham, permissions qatlamida ham qoʻshimcha tasdiqlanadi.

- FAIL-CLOSED: noaniq holatda — RUXSAT YOʻQ.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from config import Role, SUPER_ADMIN_ID
from core import database as db

logger = logging.getLogger("enginebot.permissions")


# ─────────────────────────────────────────────────────────────────────
# Action — ruxsat sʼaratoqlari
# ─────────────────────────────────────────────────────────────────────
class Action(str, Enum):
    """
    Tizimdagi barcha amallar.

    Har bir amal alohida ruxsat sifatida tekshiriladi. Yangi amal
    qoʻshish uchun shu yerga yangi qiymat qoʻshib, PERMISSIONS dict'ga
    rolga kerak boʻlsa qoʻshib qoʻyish kerak.
    """

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
    CONFIGURE_ROTATION = "configure_rotation"
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
    SET_TEMPLATE = "set_template"

    # ─── Moderator amallar (cheklangan) ─────────────────────────────
    REVIEW_USER_REQUESTS = "review_user_requests"
    WARN_USER = "warn_user"
    PAUSE_OTHER_POST = "pause_other_post"
    VIEW_QUEUE = "view_queue"

    # ─── User amallar (oʻzi uchun) ──────────────────────────────────
    REGISTER = "register"
    CREATE_OWN_POST = "create_own_post"
    EDIT_OWN_POST = "edit_own_post"
    DELETE_OWN_POST = "delete_own_post"
    VIEW_OWN_POSTS = "view_own_posts"
    EDIT_OWN_PROFILE = "edit_own_profile"
    LOGOUT = "logout"

    # ─── Hamma foydalanadigan ───────────────────────────────────────
    VIEW_HELP = "view_help"
    SEARCH_POSTS = "search_posts"


# ─────────────────────────────────────────────────────────────────────
# Ruxsat matritsasi (rol → ruxsat berilgan amallar toʻplami)
# ─────────────────────────────────────────────────────────────────────
# Eslatma: SUPER_ADMIN avtomatik HAMMA narsani qila oladi (pastda mantiq).
# Shuning uchun shu yerda super_admin'ga alohida sʼinov yozish shart emas.

_PERMISSIONS: dict[str, frozenset[Action]] = {
    Role.GUEST: frozenset({
        Action.VIEW_HELP,
        Action.REGISTER,
    }),
    Role.USER: frozenset({
        Action.VIEW_HELP,
        Action.SEARCH_POSTS,
        Action.CREATE_OWN_POST,
        Action.EDIT_OWN_POST,
        Action.DELETE_OWN_POST,
        Action.VIEW_OWN_POSTS,
        Action.EDIT_OWN_PROFILE,
        Action.LOGOUT,
    }),
    Role.MODERATOR: frozenset({
        # User huquqlari + moderator qoʻshimcha
        Action.VIEW_HELP,
        Action.SEARCH_POSTS,
        Action.CREATE_OWN_POST,
        Action.EDIT_OWN_POST,
        Action.DELETE_OWN_POST,
        Action.VIEW_OWN_POSTS,
        Action.EDIT_OWN_PROFILE,
        Action.LOGOUT,
        # Moderator
        Action.REVIEW_USER_REQUESTS,
        Action.APPROVE_USER,
        Action.WARN_USER,
        Action.PAUSE_OTHER_POST,
        Action.VIEW_QUEUE,
    }),
    Role.TENANT: frozenset({
        # User huquqlari
        Action.VIEW_HELP,
        Action.SEARCH_POSTS,
        Action.LOGOUT,
        # Tenant tugallangan huquqlar
        Action.CONNECT_CHANNEL,
        Action.DISCONNECT_CHANNEL,
        Action.CONFIGURE_ROTATION,
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
        Action.SET_TEMPLATE,
        Action.WARN_USER,
        Action.REVIEW_USER_REQUESTS,
        Action.VIEW_QUEUE,
    }),
    # SUPER_ADMIN — quyida `can()` funksiyasida HAMMASI ruxsat etilgan.
}


# ─────────────────────────────────────────────────────────────────────
# RolContext — bitta soʻrov uchun rol ma'lumoti
# ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RoleContext:
    """
    Bitta foydalanuvchi va kontekstdagi roli.

    user_id    — Telegram user ID
    role       — aniqlangan rol (Role.* dan)
    tenant_id  — qaysi tenant'da (None = global yoki tenant tanlanmagan)

    Bu obyekt bir requestning umri davomida saqlanadi (cache qilinmaydi),
    chunki rol tenantga bogʻliq holda oʻzgarishi mumkin.
    """
    user_id: int
    role: str
    tenant_id: int | None = None

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

    # 4. Oddiy user?
    user = await db.get_user(tenant_id, user_id)
    if user is not None:
        return RoleContext(user_id=user_id, role=Role.USER, tenant_id=tenant_id)

    # 5. Roʻyxatdan oʻtmagan
    return RoleContext(user_id=user_id, role=Role.GUEST, tenant_id=tenant_id)


# ─────────────────────────────────────────────────────────────────────
# Ruxsat tekshirish
# ─────────────────────────────────────────────────────────────────────
def can(ctx: RoleContext, action: Action | str) -> bool:
    """
    Foydalanuvchi shu amalni qila oladimi?

    Args:
        ctx     : resolve_role()'dan kelgan RoleContext
        action  : Action enum yoki uning string qiymati

    Returns:
        True  — ruxsat berilgan
        False — ruxsat yoʻq (default)

    XAVFSIZLIK: noaniq holatda False qaytaradi (fail-closed).
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

    allowed = _PERMISSIONS.get(ctx.role, frozenset())
    return action in allowed


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
    """
    Ruxsatni tekshirish va xato boʻlsa raise qilish.

    Handler ichida muhim joylarda ishlatiladi — defensive programming.
    """
    if not can(ctx, action):
        raise PermissionDenied(
            f"Foydalanuvchi {ctx.user_id} (rol: {ctx.role}) "
            f"'{action}' amalini bajara olmaydi."
        )


def assert_same_tenant(ctx: RoleContext, target_tenant_id: int) -> None:
    """
    Tenant izolyatsiyasi: foydalanuvchi faqat oʻz tenantida ishlay oladi.

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


def role_label(role: str) -> str:
    """Rol nomini koʻrsatish uchun (UI/audit log)."""
    return _ROLE_LABELS_UZ.get(role, f"❓ {role}")

"""Global konstantalar: statuslar, rollar, Redis kalitlari, callback prefikslari.

Barcha "sehrli satrlar" shu yerda — kod bo'ylab tarqalmasligi uchun.
(REJA.md 4-bo'limdagi jadvallar bilan mos.)
"""

from __future__ import annotations

from enum import StrEnum


# ─────────────────────────────── Rollar ───────────────────────────────
class AdminRole(StrEnum):
    SUPER = "super"          # hamma narsa
    ADMIN = "admin"          # kontent boshqaruvi
    MODERATOR = "moderator"  # faqat e'lon moderatsiyasi


# ─────────────────────────── Sotuvchi / tarif ──────────────────────────
class SellerStatus(StrEnum):
    PENDING = "pending"      # admin qo'shdi, tarif tanlamagan
    ACTIVE = "active"        # faol tarifga ega
    BLOCKED = "blocked"
    DELETED = "deleted"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"          # muddati o'tdi, xabar berilmoqda
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class AdStatus(StrEnum):
    DRAFT = "draft"
    PENDING = "pending"      # moderatsiya kutilmoqda
    ACTIVE = "active"        # navbatda
    PAUSED = "paused"        # sotuvchi yoki admin to'xtatgan
    REJECTED = "rejected"
    EXPIRED = "expired"      # tarif muddati tugagan
    DELETED = "deleted"


class PaymentStatus(StrEnum):
    PENDING = "pending"      # chek yuborilgan, admin qarori kutilmoqda
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


# ──────────────────────────── Ruxsatlar ────────────────────────────────
class PermissionKind(StrEnum):
    FULL_EXEMPT = "full_exempt"        # hech qanday shart/jazo qo'llanmaydi
    GUARD_EXEMPT = "guard_exempt"      # faqat posbon tegmaydi
    CLEANER_EXEMPT = "cleaner_exempt"  # faqat tozalovchi tegmaydi
    LINK_ALLOWED = "link_allowed"      # havola yuborishga ruxsat
    COUNTER_EXEMPT = "counter_exempt"  # N odam qo'shish sharti qo'llanmaydi


# ──────────────────────────── Guruh funksiyalari ───────────────────────
class GroupFeature(StrEnum):
    POSTING = "posting"
    COUNTER = "counter"
    GUARD = "guard"
    CLEANER = "cleaner"
    WELCOME = "welcome"


FEATURE_LABELS: dict[str, str] = {
    GroupFeature.POSTING: "📢 E'lon joylash",
    GroupFeature.COUNTER: "🧮 Sanoqchi",
    GroupFeature.GUARD: "🛡 Posbon",
    GroupFeature.CLEANER: "🧹 Tozalovchi",
    GroupFeature.WELCOME: "👋 Salomlashuv",
}

# Qisqa tugma yozuvlari (matritsa ekrani uchun)
FEATURE_SHORT: dict[str, str] = {
    GroupFeature.POSTING: "📢",
    GroupFeature.COUNTER: "🧮",
    GroupFeature.GUARD: "🛡",
    GroupFeature.CLEANER: "🧹",
    GroupFeature.WELCOME: "👋",
}

# Har funksiya qaysi bosqichda to'liq ishga tushadi (REJA.md 14-bo'lim)
FEATURE_PHASES: dict[str, int] = {
    GroupFeature.POSTING: 4,
    GroupFeature.GUARD: 6,
    GroupFeature.CLEANER: 6,
    GroupFeature.COUNTER: 7,
    GroupFeature.WELCOME: 9,
}

# Sozlama qilib qo'yish mumkin bo'lgan, lekin hali "jonli" ishlamaydigan funksiyalar
# (foydalanuvchiga ogohlantirish ko'rsatiladi)
LIVE_FEATURES: set[str] = set()  # Phase 4 da POSTING qo'shiladi


# ─────────────────────── Posbon / tozalovchi ───────────────────────────
class Penalty(StrEnum):
    WARN = "warn"
    MUTE = "mute"
    BAN = "ban"
    KICK = "kick"


class ViolationKind(StrEnum):
    LINK = "link"
    FORWARD = "forward"
    MENTION = "mention"
    NOT_SUBSCRIBED = "not_subscribed"
    COUNTER_NOT_DONE = "counter_not_done"
    FLOOD = "flood"
    BANNED_WORD = "banned_word"


class CleanupKind(StrEnum):
    JOIN_LEAVE = "join_leave"
    SERVICE = "service"
    LINK = "link"
    VIOLATION = "violation"
    OLD_AD = "old_ad"
    RETENTION = "retention"


# ──────────────────────────── Sanoqchi ─────────────────────────────────
class CounterMode(StrEnum):
    SOFT = "soft"   # xabar o'chiriladi + ogohlantirish
    HARD = "hard"   # yangi a'zo mute qilinadi


class InviteSource(StrEnum):
    LINK = "link"         # shaxsiy invite link orqali
    ADDED_BY = "added_by"  # kimdir to'g'ridan-to'g'ri qo'shdi
    MANUAL = "manual"      # admin qo'lda
    ADMIN = "admin"        # admin tomonidan tuzatish


# ──────────────────────────── Referal ──────────────────────────────────
class ReferralTrigger(StrEnum):
    SIGNUP = "signup"
    FIRST_PAYMENT = "first_payment"


class BonusType(StrEnum):
    DAYS = "days"          # bepul kunlar
    DISCOUNT = "discount"  # chegirma (%)
    BALANCE = "balance"    # balansga pul


# ──────────────────────────── DB / Redis kalitlari ─────────────────────
class RedisKey:
    SETTINGS_VERSION = "shopbot:settings:version"
    SETTINGS_SNAPSHOT = "shopbot:settings:snapshot"
    POSTING_LOCK = "shopbot:lock:posting"
    GROUP_LAST_POST = "shopbot:group:{group_id}:last_post"
    THROTTLE = "shopbot:throttle:{scope}:{key}"
    BROADCAST_QUEUE = "shopbot:broadcast:queue"
    HEARTBEAT = "shopbot:heartbeat:{name}"


# ──────────────────────────── Callback prefikslari ─────────────────────
class CB:
    """Inline tugma callback_data prefikslari (aiogram CallbackData fabrikalari uchun)."""

    ADMIN_MENU = "adm"        # boshqaruv paneli navigatsiyasi
    GROUP = "grp"             # guruh sozlamalari
    CATEGORY = "cat"          # toifalar
    SELLER = "slr"            # sotuvchilar
    AD = "ad"                 # e'lonlar / moderatsiya
    TARIFF = "trf"            # tariflar
    PAYMENT = "pay"           # to'lovlar / cheklar
    REFERRAL = "ref"          # referal
    COUNTER = "cnt"           # sanoqchi
    GUARD = "grd"             # posbon
    CLEANER = "cln"           # tozalovchi
    PERMISSION = "prm"        # ruxsatlar
    USERS = "usr"             # foydalanuvchilar (mute/ban)
    TEXTS = "txt"             # bot matnlari
    ERRORS = "err"            # xatolar jurnali
    ADMINS = "adm_users"      # adminlarni boshqarish
    SETTINGS = "cfg"          # global sozlamalar
    SELLER_MENU = "sm"        # sotuvchi paneli
    USER_MENU = "um"          # foydalanuvchi paneli


# ──────────────────────────── Standart qiymatlar ───────────────────────
DEFAULT_INTERVAL_SEC = 1800          # 30 daqiqa
MIN_INTERVAL_SEC = 60                # Telegram limiti: 1 guruhga 20 xabar/daqiqa
MAX_INTERVAL_SEC = 864000            # 10 kun: admin tanlaydigan intervalning yuqori chegarasi
MIN_JITTER_PERCENT = 0
MAX_JITTER_PERCENT = 30                # foiz/vaqt matematikasi: 10x oshirilmaydi
MAX_DAILY_POST_LIMIT = 5000
MAX_PHOTOS_PER_ALBUM = 10            # Telegram bir albomda maksimal 10 rasm
MAX_TEXT_LEN = 4096
MAX_CAPTION_LEN = 1024
MAX_ADS_PER_PAGE = 8
BROADCAST_RATE_PER_SEC = 25          # ~30 msg/s limitidan past
GROUP_RATE_MIN_GAP_SEC = 2.0         # bitta guruhga minimal oraliq

"""Ma'lumotlar bazasi modellari.

Jadvallar REJA.md ning 4-bo'limiga to'liq mos keladi (9 guruh):
  4.1 Yadro · 4.2 Guruhlar/Toifalar · 4.3 Sotuvchilar/Tariflar
  4.4 E'lonlar/Navbat · 4.5 To'lovlar · 4.6 Referal · 4.7 Sanoqchi
  4.8 Posbon/Tozalovchi · 4.9 Statistika/Broadcast

Muhim qoidalar:
  * Telegram ID'lar — BigInteger (int32 ga sig'maydi).
  * Pul — Numeric(12, 2).
  * Barcha statuslar — `app.constants` dagi StrEnum qiymatlari (String ustunlar).
  * Vaqt — har doim UTC (timezone=True).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import (
    AdminRole,
    AdStatus,
    ApplicationStatus,
    BonusType,
    CleanupKind,
    CounterMode,
    InviteSource,
    PaymentStatus,
    Penalty,
    PermissionKind,
    ReferralTrigger,
    SellerStatus,
    SubscriptionStatus,
)
from app.db.base import Base, JSONType, TimestampMixin


# ═══════════════════════════════════════════════════════════════════════
#  4.1. YADRO
# ═══════════════════════════════════════════════════════════════════════
class User(Base, TimestampMixin):
    """Barcha foydalanuvchilar: admin, sotuvchi, guruh a'zosi."""

    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    first_name: Mapped[Optional[str]] = mapped_column(String(128))
    last_name: Mapped[Optional[str]] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(8), default="uz")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text)
    private_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Migratsiyadan oldin shaxsiy/guruh start tarixini ajratib bo'lmaydi.
    # Eski foydalanuvchilar bonus olmasin; yangi yaratilganlar uchun false.
    referral_legacy: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    broadcast_opt_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Eslatma: `Seller` bilan ORM relationship ATAYLAB yo'q.
    # Sabab: sotuvchini admin qo'lda qo'shishi mumkin — u paytda foydalanuvchi
    # hali botga /start bosmagan bo'ladi (users jadvalida yozuv yo'q).
    # Shu sababli sotuvchi `seller_service.get_seller()` orqali olinadi.

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.user_id} @{self.username}>"


class Admin(Base, TimestampMixin):
    """Adminlar va ularning rollari (REJA.md 1.2/#13)."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default=AdminRole.ADMIN)
    title: Mapped[Optional[str]] = mapped_column(String(64))
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class GroupAdmin(Base, TimestampMixin):
    """Guruh darajasidagi adminlar (guruh ichidan tayinlanadi)."""

    __tablename__ = "group_admins"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_admin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(16), default=AdminRole.MODERATOR)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger)


class Setting(Base, TimestampMixin):
    """Global sozlamalar (key → JSON qiymat). O'zgarishda kesh versiyasi oshadi."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[Any]] = mapped_column(JSONType)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    comment: Mapped[Optional[str]] = mapped_column(String(255))


class BotText(Base, TimestampMixin):
    """Bot matnlari (admin panelda tahrirlanadi)."""

    __tablename__ = "bot_texts"
    __table_args__ = (UniqueConstraint("key", "lang", name="uq_bot_text_key_lang"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    lang: Mapped[str] = mapped_column(String(8), default="uz")
    text: Mapped[str] = mapped_column(Text)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)  # admin o'zgartirganmi
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger)


class ActionLog(Base, TimestampMixin):
    """Audit: kim nima o'zgartirdi (REJA.md 11.1)."""

    __tablename__ = "action_log"
    __table_args__ = (Index("ix_action_log_actor_created", "actor_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[Optional[str]] = mapped_column(String(64))
    entity_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    before: Mapped[Optional[Any]] = mapped_column(JSONType)
    after: Mapped[Optional[Any]] = mapped_column(JSONType)


class ErrorLog(Base, TimestampMixin):
    """Xatolar jurnali (admin panelda ko'rinadi)."""

    __tablename__ = "error_log"
    __table_args__ = (Index("ix_error_log_source_created", "source", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="ERROR")
    source: Mapped[str] = mapped_column(String(64), index=True)
    group_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[Optional[str]] = mapped_column(Text)
    context: Mapped[Optional[Any]] = mapped_column(JSONType)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[int]] = mapped_column(BigInteger)


# ═══════════════════════════════════════════════════════════════════════
#  4.2. GURUHLAR VA TOIFALAR
# ═══════════════════════════════════════════════════════════════════════
class Group(Base, TimestampMixin):
    """Guruhlar (faqat supergroup'da to'liq ishlaydi — REJA.md 1.2/#3)."""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    username: Mapped[Optional[str]] = mapped_column(String(64))
    chat_type: Mapped[Optional[str]] = mapped_column(String(32))
    is_supergroup: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    bot_rights: Mapped[Optional[Any]] = mapped_column(JSONType)  # can_delete_messages va h.k.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    paused_reason: Mapped[Optional[str]] = mapped_column(String(32))
    member_count: Mapped[Optional[int]] = mapped_column(Integer)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    settings: Mapped[Optional["GroupSettings"]] = relationship(
        back_populates="group", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
    rotation: Mapped[Optional["GroupRotation"]] = relationship(
        back_populates="group", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
    categories: Mapped[list["Category"]] = relationship(back_populates="group", lazy="raise")

    @property
    def display(self) -> str:
        return self.title or (f"@{self.username}" if self.username else str(self.tg_chat_id))


class GroupSettings(Base, TimestampMixin):
    """Har guruh uchun alohida sozlamalar (REJA.md: asosiy qoida)."""

    __tablename__ = "group_settings"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    # Funksiya kalitlari (REJA.md 1 — "har funksiyani alohida to'xtatish")
    posting_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    counter_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    guard_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cleaner_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Joylash
    interval_sec: Mapped[int] = mapped_column(Integer, default=1800)
    jitter_percent: Mapped[int] = mapped_column(Integer, default=10)
    daily_post_limit: Mapped[int] = mapped_column(Integer, default=50)
    quiet_start: Mapped[Optional[str]] = mapped_column(String(5))  # "23:00"
    quiet_end: Mapped[Optional[str]] = mapped_column(String(5))    # "08:00"
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
    protect_content: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[Optional[Any]] = mapped_column(JSONType)  # kelgusi sozlamalar uchun

    group: Mapped["Group"] = relationship(back_populates="settings")


class GroupRotation(Base, TimestampMixin):
    """Guruh darajasidagi joylash holati (restartga chidamli)."""

    __tablename__ = "group_rotation"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    last_post_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_post_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )
    today_count: Mapped[int] = mapped_column(Integer, default=0)
    today_date: Mapped[Optional[date]] = mapped_column(Date)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    error_streak: Mapped[int] = mapped_column(Integer, default=0)

    group: Mapped["Group"] = relationship(back_populates="rotation")


class Category(Base, TimestampMixin):
    """Toifalar; har toifaga bitta tayyor guruh biriktiriladi."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    emoji: Mapped[Optional[str]] = mapped_column(String(16))
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=1000)
    interval_override: Mapped[Optional[int]] = mapped_column(Integer)  # guruh intervalini bekor qilish
    moderation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger)

    group: Mapped[Optional["Group"]] = relationship(back_populates="categories", lazy="selectin")
    rotation: Mapped[Optional["CategoryRotation"]] = relationship(
        back_populates="category", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )


class RequiredChannel(Base, TimestampMixin):
    """Majburiy obuna kanallari (global yoki guruh bo'yicha)."""

    __tablename__ = "required_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(16), default="global")  # global | group
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    channel_tg_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    username: Mapped[Optional[str]] = mapped_column(String(64))
    title: Mapped[Optional[str]] = mapped_column(String(255))
    invite_link: Mapped[Optional[str]] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger)


class Permission(Base, TimestampMixin):
    """Ruxsatlar: "bot unga tegmaydi" (REJA.md 1 — Ruxsatlar)."""

    __tablename__ = "permissions"
    __table_args__ = (
        Index("ix_permissions_lookup", "user_id", "group_id", "kind"),
        # NULL global scope uchun alohida indeks: ikkita aktiv nusxa qaytarib
        # olingan ruxsatni tasodifan qayta faol qoldirmasin.
        Index("uq_permissions_group_active", "user_id", "group_id", "kind", unique=True,
              postgresql_where=text("is_active AND group_id IS NOT NULL"),
              sqlite_where=text("is_active AND group_id IS NOT NULL")),
        Index("uq_permissions_global_active", "user_id", "kind", unique=True,
              postgresql_where=text("is_active AND group_id IS NULL"),
              sqlite_where=text("is_active AND group_id IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # NULL = barcha guruhlarda
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default=PermissionKind.FULL_EXEMPT)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    granted_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


# ═══════════════════════════════════════════════════════════════════════
#  4.3. SOTUVCHILAR, TARIFLAR, OBUNALAR
# ═══════════════════════════════════════════════════════════════════════
class Seller(Base, TimestampMixin):
    """Sotuvchilar (faqat admin qo'shadi)."""

    __tablename__ = "sellers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    phone: Mapped[Optional[str]] = mapped_column(String(32))
    contact: Mapped[Optional[str]] = mapped_column(String(128))  # @username yoki havola
    status: Mapped[str] = mapped_column(String(16), default=SellerStatus.PENDING, index=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_code: Mapped[Optional[str]] = mapped_column(String(16), unique=True, index=True)
    referred_by: Mapped[Optional[int]] = mapped_column(BigInteger)  # referrer user_id
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    note: Mapped[Optional[str]] = mapped_column(Text)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text)

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="seller", lazy="selectin"
    )

    @property
    def active_subscription(self) -> Optional["Subscription"]:
        """Amaldagi (muddati o'tmagan) obuna — bo'lmasa None."""
        from app.utils.time import ensure_aware, utcnow

        now = utcnow()
        for sub in self.subscriptions:
            expires = ensure_aware(sub.expires_at)
            if sub.status == SubscriptionStatus.ACTIVE and expires is not None and expires > now:
                return sub
        return None


class SellerApplication(Base, TimestampMixin):
    """Shaxsiy chatdan berilgan sotuvchilik arizasi (tarifdan mustaqil).

    Tarix saqlanadi, lekin bir foydalanuvchida faqat bitta ochiq ariza bo'lishi
    qisman UNIQUE indeks bilan bazaning o'zida ham kafolatlanadi.
    """

    __tablename__ = "seller_applications"
    __table_args__ = (
        Index("ix_seller_applications_user_created", "user_id", "created_at"),
        Index("ix_seller_applications_status_created", "status", "created_at"),
        Index(
            "uq_seller_applications_pending_user", "user_id", unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Seller kabi users ga FK yo'q: tarixni/sotuvchini user yozuviga bog'lamaymiz.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    contact_type: Mapped[str] = mapped_column(String(16), nullable=False)  # username | phone
    contact_value: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=ApplicationStatus.PENDING, nullable=False)
    seller_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sellers.id", ondelete="SET NULL"), index=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    reject_reason: Mapped[Optional[str]] = mapped_column(String(500))


class Tariff(Base, TimestampMixin):
    """Tariflar: nom, narx, muddat, limitlar, qaysi guruh/toifalar uchun."""

    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    duration_days: Mapped[int] = mapped_column(Integer, default=30)
    max_ads: Mapped[int] = mapped_column(Integer, default=5)          # e'lonlar soni
    max_photos: Mapped[int] = mapped_column(Integer, default=3)       # har e'londa rasmlar
    allowed_category_ids: Mapped[Optional[Any]] = mapped_column(JSONType)  # None = hammasi
    allowed_group_ids: Mapped[Optional[Any]] = mapped_column(JSONType)     # None = hammasi
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=1000)
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)    # sinov tarifi


class Subscription(Base, TimestampMixin):
    """Sotuvchining obunasi: muddat va limitlar."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_seller_status", "seller_id", "status"),
        Index("ix_subscriptions_expires", "expires_at", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"))
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default=SubscriptionStatus.ACTIVE)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ads_limit: Mapped[int] = mapped_column(Integer, default=0)
    ads_used: Mapped[int] = mapped_column(Integer, default=0)
    granted_by: Mapped[Optional[int]] = mapped_column(BigInteger)   # admin bergan bo'lsa
    payment_id: Mapped[Optional[int]] = mapped_column(Integer)
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expired_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    seller: Mapped["Seller"] = relationship(back_populates="subscriptions")
    tariff: Mapped["Tariff"] = relationship(lazy="selectin")

    @property
    def is_valid(self) -> bool:
        from app.utils.time import ensure_aware, utcnow

        expires = ensure_aware(self.expires_at)
        return (
            self.status == SubscriptionStatus.ACTIVE
            and expires is not None
            and expires > utcnow()
        )

    @property
    def ads_left(self) -> int:
        return max(0, self.ads_limit - self.ads_used)


# ═══════════════════════════════════════════════════════════════════════
#  4.4. E'LONLAR VA NAVBAT
# ═══════════════════════════════════════════════════════════════════════
class Ad(Base, TimestampMixin):
    """Sotuvchi e'lonlari."""

    __tablename__ = "ads"
    __table_args__ = (
        Index("ix_ads_category_status_pos", "category_id", "status", "position"),
        Index("ix_ads_seller_status", "seller_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    contact_type: Mapped[str] = mapped_column(String(16), default="username")  # username|url|phone
    contact_value: Mapped[Optional[str]] = mapped_column(String(255))
    contact_label: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=AdStatus.DRAFT, index=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=1000)     # navbat tartibi
    post_count: Mapped[int] = mapped_column(Integer, default=0)      # necha marta joylangan
    last_posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_eligible_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[int]] = mapped_column(BigInteger)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    photos: Mapped[list["AdPhoto"]] = relationship(
        back_populates="ad",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="AdPhoto.position",
    )
    category: Mapped["Category"] = relationship(lazy="selectin")

    @property
    def caption(self) -> str:
        """E'lon izohi (albom izohi / xabar matni)."""
        lines = [f"<b>{self.title}</b>"]
        if self.price is not None:
            # Valyuta belgisi (`so'm`, `$`, ...) — `fmt_amount` orqali (app/utils/text.py)
            from app.utils.text import fmt_amount

            lines.append(f"💰 Narx: <b>{fmt_amount(self.price, self.currency or 'UZS')}</b>")
        if self.description:
            lines.append(f"\n{self.description}")
        if self.contact_value and self.contact_type == "phone":
            lines.append(f"\n📞 {self.contact_value}")
        if self.category and self.category.name:
            lines.append(f"\n#{self.category.name.replace(' ', '_')}")
        return "\n".join(lines)[:1024]


class AdPhoto(Base, TimestampMixin):
    """E'lon rasmlari — faqat Telegram file_id saqlanadi (disk tejash)."""

    __tablename__ = "ad_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[str] = mapped_column(String(255))
    file_unique_id: Mapped[Optional[str]] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)

    ad: Mapped["Ad"] = relationship(back_populates="photos")


class CategoryRotation(Base, TimestampMixin):
    """Toifa navbat kursori — aylanma joylashning yuragi (REJA.md 9)."""

    __tablename__ = "category_rotation"

    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True
    )
    cursor_ad_id: Mapped[Optional[int]] = mapped_column(Integer)  # oxirgi joylangan e'lon
    last_post_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    next_post_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)

    category: Mapped["Category"] = relationship(back_populates="rotation")


class PostedMessage(Base, TimestampMixin):
    """Guruhga joylangan xabarlar (eski e'lonlarni o'chirish uchun)."""

    __tablename__ = "posted_messages"
    __table_args__ = (
        Index("ix_posted_messages_group_sent", "group_id", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    message_ids: Mapped[Optional[Any]] = mapped_column(JSONType)  # [albom_id..., tugma_id]
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    delete_after_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_error: Mapped[Optional[str]] = mapped_column(Text)


class ModerationLog(Base, TimestampMixin):
    """Moderatsiya qarorlari tarixi."""

    __tablename__ = "moderation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ad_id: Mapped[int] = mapped_column(ForeignKey("ads.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    decision: Mapped[str] = mapped_column(String(16))  # approved | rejected | revised
    reason: Mapped[Optional[str]] = mapped_column(Text)


class PostLog(Base, TimestampMixin):
    """Joylash tarixi (statistika + xatolar)."""

    __tablename__ = "post_log"
    __table_args__ = (
        Index("ix_post_log_group_created", "group_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(BigInteger, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(Integer)
    ad_id: Mapped[Optional[int]] = mapped_column(Integer)
    seller_id: Mapped[Optional[int]] = mapped_column(Integer)
    message_ids: Mapped[Optional[Any]] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | skipped
    error: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)


# ═══════════════════════════════════════════════════════════════════════
#  4.5. TO'LOVLAR
# ═══════════════════════════════════════════════════════════════════════
class PaymentMethod(Base, TimestampMixin):
    """To'lov rekvizitlari (bir nechta karta, aylanma)."""

    __tablename__ = "payment_methods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))                 # masalan "Uzcard"
    card_number: Mapped[str] = mapped_column(String(32))
    holder: Mapped[Optional[str]] = mapped_column(String(128))
    bank: Mapped[Optional[str]] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    note: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=1000)


class Payment(Base, TimestampMixin):
    """To'lovlar: chek → admin tasdig'i → obuna (REJA.md 8.2)."""

    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_status_created", "status", "created_at"),
        # Takroriy chekni ushlash: NULL qiymatlar cheklanmaydi (PG va SQLite'da)
        UniqueConstraint("receipt_unique_hash", name="uq_payments_receipt_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(ForeignKey("sellers.id", ondelete="CASCADE"), index=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id", ondelete="RESTRICT"))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))  # bankka to'lanadigan qism
    base_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"),
                                                 server_default=text("0"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"),
                                                     server_default=text("0"))
    balance_used: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"),
                                                  server_default=text("0"))
    discount_bonus_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("referral_bonus_log.id", ondelete="RESTRICT")
    )
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    method_id: Mapped[Optional[int]] = mapped_column(ForeignKey("payment_methods.id", ondelete="SET NULL"))
    receipt_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    receipt_unique_hash: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    is_duplicate_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=PaymentStatus.PENDING, index=True)
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reason: Mapped[Optional[str]] = mapped_column(Text)   # rad etish sababi
    subscription_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )

    seller: Mapped["Seller"] = relationship(lazy="selectin")
    tariff: Mapped["Tariff"] = relationship(lazy="selectin")


# ═══════════════════════════════════════════════════════════════════════
#  4.6. REFERAL (sanoqchidan alohida)
# ═══════════════════════════════════════════════════════════════════════
class ReferralSetting(Base, TimestampMixin):
    """Referal sozlamalari (key → JSON)."""

    __tablename__ = "referral_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[Any]] = mapped_column(JSONType)
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger)


class Referral(Base, TimestampMixin):
    """Takliflar: bir odam faqat bir marta sanaladi."""

    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referee_id", name="uq_referral_referee"),
        Index("ix_referrals_referrer_status", "referrer_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referee_id: Mapped[int] = mapped_column(BigInteger)
    code: Mapped[Optional[str]] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16), default=ReferralTrigger.SIGNUP)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|applied|rejected
    trigger_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_payment_id: Mapped[Optional[int]] = mapped_column(Integer)
    bonus_type: Mapped[Optional[str]] = mapped_column(String(16), default=BonusType.DAYS)
    bonus_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ReferralBonusLog(Base, TimestampMixin):
    """Berilgan bonuslar tarixi: har referal bir martagina bonus oladi."""

    __tablename__ = "referral_bonus_log"
    __table_args__ = (UniqueConstraint("referral_id", name="uq_referral_bonus_once"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referral_id: Mapped[int] = mapped_column(ForeignKey("referrals.id", ondelete="CASCADE"))
    seller_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    bonus_type: Mapped[str] = mapped_column(String(16))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)  # qo'lda berilgan bo'lsa
    reserved_payment_id: Mapped[Optional[int]] = mapped_column(Integer)  # chegirma uchun chek (qaytariladi)
    redeemed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ═══════════════════════════════════════════════════════════════════════
#  4.7. SANOQCHI (har guruhda alohida)
# ═══════════════════════════════════════════════════════════════════════
class CounterSetting(Base, TimestampMixin):
    """Sanoqchi sozlamalari (REJA.md 8.4)."""

    __tablename__ = "counter_settings"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Eski matritsa sozlamasi migratsiyadan keyin birdan jazo bermasin.
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    required_n: Mapped[int] = mapped_column(Integer, default=3)
    mode: Mapped[str] = mapped_column(String(8), default=CounterMode.SOFT)
    link_member_limit: Mapped[int] = mapped_column(Integer, default=20, server_default=text("20"))
    min_stay_minutes: Mapped[int] = mapped_column(Integer, default=10)  # soxta akkauntlarga qarshi
    max_per_day: Mapped[int] = mapped_column(Integer, default=20)
    count_sources: Mapped[Optional[Any]] = mapped_column(JSONType)  # {"link":true,"added_by":true}
    require_subscription: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_inviter: Mapped[bool] = mapped_column(Boolean, default=True)


class InviteLink(Base, TimestampMixin):
    """Foydalanuvchilarning shaxsiy taklif havolalari (pool bilan)."""

    __tablename__ = "invite_links"
    __table_args__ = (
        Index("ix_invite_links_group_user", "group_id", "user_id"),
        Index("uq_invite_links_active_owner", "group_id", "user_id", unique=True,
              postgresql_where=text("is_active"), sqlite_where=text("is_active")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    invite_link: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[Optional[str]] = mapped_column(String(32))
    join_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class InviteEvent(Base, TimestampMixin):
    """Kim kimni qo'shgani — bir odam bir guruhda bir marta sanaladi."""

    __tablename__ = "invite_events"
    __table_args__ = (
        UniqueConstraint("group_id", "invitee_id", name="uq_invite_event_once"),
        Index("ix_invite_events_inviter_created", "inviter_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    inviter_id: Mapped[Optional[int]] = mapped_column(BigInteger, index=True)
    invitee_id: Mapped[int] = mapped_column(BigInteger, index=True)
    invite_link: Mapped[Optional[str]] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16), default=InviteSource.LINK)
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    counted: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_reason: Mapped[Optional[str]] = mapped_column(String(64))


class CounterTotal(Base, TimestampMixin):
    """Jamlanma hisob (tez o'qish uchun)."""

    __tablename__ = "counter_totals"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    counted: Mapped[int] = mapped_column(Integer, default=0)
    bonus_counted: Mapped[int] = mapped_column(Integer, default=0)  # tashrif buyurganlar (bonus)
    is_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)  # shart bajarildi
    unlocked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_count_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CounterAudit(Base, TimestampMixin):
    """Admin qo'lda qo'shgani/ayirgani tarixi."""

    __tablename__ = "counter_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[Optional[str]] = mapped_column(String(255))
    admin_id: Mapped[Optional[int]] = mapped_column(BigInteger)


class CounterJoinRequest(Base, TimestampMixin):
    """Join request hali a'zo emas: atributsiya faqat haqiqiy kirganda olinadi."""

    __tablename__ = "counter_join_requests"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    invite_link: Mapped[str] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CounterMessageCheck(Base, TimestampMixin):
    """Har xabar uchun sanoqchi tekshiruvi (dry-run ham boshqa filtrni to'smaydi)."""

    __tablename__ = "counter_message_checks"
    __table_args__ = (UniqueConstraint("group_id", "message_id", name="uq_counter_message_check"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    issue: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # dry_run | running | deleted | failed | skipped
    error: Mapped[str | None] = mapped_column(String(255))


class CounterRestriction(Base, TimestampMixin):
    """Faqat botning o'zi qo'ygan sanoqchi mute'ini xavfsiz ochish uchun."""

    __tablename__ = "counter_restrictions"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # running | active | uncertain | released
    issue: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(String(255))


# ═══════════════════════════════════════════════════════════════════════
#  4.8. POSBON VA TOZALOVCHI
# ═══════════════════════════════════════════════════════════════════════
class GuardSetting(Base, TimestampMixin):
    """Posbon sozlamalari (REJA.md 8.5)."""

    __tablename__ = "guard_settings"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)   # faqat log, jazo yo'q
    require_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    require_counter: Mapped[bool] = mapped_column(Boolean, default=False)
    link_filter: Mapped[bool] = mapped_column(Boolean, default=True)
    forward_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    mention_filter: Mapped[bool] = mapped_column(Boolean, default=False)
    banned_words: Mapped[Optional[Any]] = mapped_column(JSONType)      # ["so'z1", ...]
    allowed_domains: Mapped[Optional[Any]] = mapped_column(JSONType)   # ["olx.uz", ...]
    penalty: Mapped[str] = mapped_column(String(8), default=Penalty.WARN)
    mute_minutes: Mapped[int] = mapped_column(Integer, default=60)
    warn_limit: Mapped[int] = mapped_column(Integer, default=3)
    escalate: Mapped[Optional[Any]] = mapped_column(JSONType)  # {"warn":3,"mute_minutes":[10,60,1440]}
    exemption_for_admins: Mapped[bool] = mapped_column(Boolean, default=True)


class Warning(Base, TimestampMixin):
    """Ogohlantirish hisobi."""

    __tablename__ = "warnings"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    last_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Violation(Base, TimestampMixin):
    """Qoidabuzarliklar tarixi."""

    __tablename__ = "violations"
    __table_args__ = (
        Index("ix_violations_group_user_created", "group_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(32))
    message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    text_excerpt: Mapped[Optional[str]] = mapped_column(String(255))
    action: Mapped[Optional[str]] = mapped_column(String(16))  # warn|mute|ban|delete|logged
    penalty_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False)


class Restriction(Base, TimestampMixin):
    """Mute/ban ro'yxati (REJA.md 1 — Foydalanuvchilar ro'yxati)."""

    __tablename__ = "restrictions"
    __table_args__ = (
        Index("ix_restrictions_group_user", "group_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kind: Mapped[str] = mapped_column(String(8))  # mute | ban | kick
    until_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # None = doimiy
    reason: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    lifted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lifted_by: Mapped[Optional[int]] = mapped_column(BigInteger)


class GroupMessageAction(Base, TimestampMixin):
    """Har xabarga yagona qaror: webhook dublikatini va ikki worker amalini to'sadi.

    `running` natijasi noma'lum qolsa avtomatik qayta urinilmaydi: Telegram API'da
    idempotency key yo'q, noto'g'ri takroriy jazo xavfli.
    """

    __tablename__ = "group_message_actions"
    __table_args__ = (
        UniqueConstraint("group_id", "message_id", name="uq_group_message_action"),
        Index("ix_group_message_actions_due", "status", "due_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(16))  # guard | cleaner
    kind: Mapped[str] = mapped_column(String(32))
    planned_action: Mapped[str] = mapped_column(String(16))  # log | delete | warn | mute | ban
    status: Mapped[str] = mapped_column(String(16))  # pending | running | done | failed | skipped
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(String(500))


class CleanerSetting(Base, TimestampMixin):
    """Tozalovchi sozlamalari (REJA.md 8.6)."""

    __tablename__ = "cleaner_settings"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # Eskidan yoqilgan eski post tozalashlari migratsiyadan keyin ham ishlaydi;
    # yangi siyosatlar esa Python'da dry-run bilan yaratiladi.
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, server_default=false())
    delete_join_leave: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_service: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_links: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_violations: Mapped[bool] = mapped_column(Boolean, default=True)
    delete_old_ads: Mapped[bool] = mapped_column(Boolean, default=True)
    keep_last_ads: Mapped[int] = mapped_column(Integer, default=1)   # har e'londan nechta qoladi
    delete_after_seconds: Mapped[Optional[int]] = mapped_column(Integer)  # kirdi-chiqdi uchun
    keep_pinned: Mapped[bool] = mapped_column(Boolean, default=True)
    is_hard_delete: Mapped[bool] = mapped_column(Boolean, default=True)  # o'chirish yoki tahrirlash


class CleanupLog(Base, TimestampMixin):
    """Tozalash statistikasi."""

    __tablename__ = "cleanup_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32), default=CleanupKind.RETENTION)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[Optional[Any]] = mapped_column(JSONType)


# ═══════════════════════════════════════════════════════════════════════
#  4.9. STATISTIKA VA BROADCAST
# ═══════════════════════════════════════════════════════════════════════
class StatsDaily(Base, TimestampMixin):
    """Kunlik jamlanma (grafiklar tez chiqishi uchun)."""

    __tablename__ = "stats_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=0)  # 0 = umumiy
    posts: Mapped[int] = mapped_column(Integer, default=0)
    active_ads: Mapped[int] = mapped_column(Integer, default=0)
    joins: Mapped[int] = mapped_column(Integer, default=0)
    leaves: Mapped[int] = mapped_column(Integer, default=0)
    violations: Mapped[int] = mapped_column(Integer, default=0)
    deleted_msgs: Mapped[int] = mapped_column(Integer, default=0)
    new_sellers: Mapped[int] = mapped_column(Integer, default=0)
    payments_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"))


class Broadcast(Base, TimestampMixin):
    """Tasdiqlangandan keyin manzillari muzlatilgan ommaviy xabar."""

    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[Optional[str]] = mapped_column(Text)
    photo_file_id: Mapped[Optional[str]] = mapped_column(String(255))
    target: Mapped[str] = mapped_column(String(16), default="sellers")  # all|sellers|admins
    total: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class BroadcastTarget(Base, TimestampMixin):
    """Har qabul qiluvchi holati: tarmoq uzilganda noma'lum natija qayta yuborilmaydi."""

    __tablename__ = "broadcast_targets"
    __table_args__ = (
        Index("ix_broadcast_targets_broadcast_status", "broadcast_id", "status"),
        UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_targets_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|running|sent|failed|uncertain
    error: Mapped[Optional[str]] = mapped_column(String(255))
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ─────────────────────── Barcha modellar ro'yxati ──────────────────────
__all__ = [
    # 4.1 Yadro
    "User", "Admin", "GroupAdmin", "Setting", "BotText", "ActionLog", "ErrorLog",
    # 4.2 Guruhlar / toifalar
    "Group", "GroupSettings", "GroupRotation", "Category", "RequiredChannel", "Permission",
    # 4.3 Sotuvchi / tarif
    "Seller", "Tariff", "Subscription",
    # 4.4 E'lon / navbat
    "Ad", "AdPhoto", "CategoryRotation", "PostedMessage", "ModerationLog", "PostLog",
    # 4.5 To'lov
    "PaymentMethod", "Payment",
    # 4.6 Referal
    "ReferralSetting", "Referral", "ReferralBonusLog",
    # 4.7 Sanoqchi
    "CounterSetting", "InviteLink", "InviteEvent", "CounterTotal", "CounterAudit",
    "CounterJoinRequest", "CounterMessageCheck", "CounterRestriction",
    # 4.8 Posbon / tozalovchi
    "GuardSetting", "Warning", "Violation", "Restriction", "CleanerSetting", "CleanupLog", "GroupMessageAction",
    # 4.9 Statistika / broadcast
    "StatsDaily", "Broadcast", "BroadcastTarget",
]

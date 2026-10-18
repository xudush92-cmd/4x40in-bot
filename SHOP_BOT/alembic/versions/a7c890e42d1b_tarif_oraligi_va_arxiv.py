"""Shaxsiy tarif oralig'i, xarid shartlari va admin pauzasi.

Revision ID: a7c890e42d1b
Revises: 871c32b421d5
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

JSONType = sa.JSON().with_variant(JSONB, "postgresql")

revision: str = "a7c890e42d1b"
down_revision: str | None = "871c32b421d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tariffs", sa.Column("interval_sec", sa.Integer(), nullable=False, server_default="1800"))
    op.add_column("subscriptions", sa.Column("terms", JSONType, nullable=True))
    op.add_column("payments", sa.Column("terms", JSONType, nullable=True))
    op.add_column("ads", sa.Column("admin_paused", sa.Boolean(), nullable=False,
                                    server_default=sa.false()))
    op.add_column("free_ads", sa.Column("admin_paused", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))
    op.create_table(
        "subscription_grants",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("tariff_id", sa.Integer(), nullable=False),
        sa.Column("terms", JSONType, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payment_id", sa.Integer()),
        sa.Column("granted_by", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_subscription_grants_subscription_id", "subscription_grants", ["subscription_id"])
    op.create_index("ix_subscription_grants_user_id", "subscription_grants", ["user_id"])
    bind = op.get_bind()
    # Eskidagi guruh oralig'idan faol tariflar uchun konservativ boshlang'ich
    # qiymat; keyingi tahrirlarda guruh sozlamasi hech qachon o'qilmaydi.
    for tariff_id, gap in bind.execute(sa.text("""
        SELECT s.tariff_id, MAX(gs.interval_sec)
        FROM subscriptions s JOIN ads a ON a.seller_id = s.seller_id
        JOIN categories c ON c.id = a.category_id
        JOIN group_settings gs ON gs.group_id = c.group_id
        GROUP BY s.tariff_id
    """)):
        bind.execute(sa.text("UPDATE tariffs SET interval_sec = :gap WHERE id = :id"),
                     {"gap": max(60, min(int(gap or 1800), 86400)), "id": tariff_id})

    now = datetime.now(UTC)
    insert_grant = sa.text("""
        INSERT INTO subscription_grants
        (subscription_id, user_id, tariff_id, terms, starts_at, expires_at,
         payment_id, granted_by, created_at, updated_at)
        VALUES (:subscription_id, :user_id, :tariff_id, :terms, :starts_at, :expires_at,
                :payment_id, :granted_by, :created_at, :updated_at)
    """).bindparams(sa.bindparam("terms", type_=JSONType))
    set_terms = sa.text("UPDATE subscriptions SET terms = :terms WHERE id = :id").bindparams(
        sa.bindparam("terms", type_=JSONType))
    rows = bind.execute(sa.text("""
        SELECT s.id, seller.user_id, s.tariff_id, s.ads_limit, s.starts_at, s.expires_at,
               s.payment_id, s.granted_by, t.name, t.price, t.currency, t.duration_days,
               t.max_photos, t.interval_sec, t.allowed_group_ids, t.allowed_category_ids, t.is_trial
        FROM subscriptions s JOIN sellers seller ON seller.id = s.seller_id
        JOIN tariffs t ON t.id = s.tariff_id
    """)).all()
    for (sub_id, user_id, tariff_id, limit, starts, expires, payment, granted,
         name, price, currency, days, photos, interval, groups, categories, trial) in rows:
        # JSON SQLite da string, PostgreSQL da dict/list; sa.JSON ResultProcessor
        # ushbu text() natijasiga ulanmagani uchun ikki formatni ham o'qiymiz.
        import json
        terms = {
            "name": name, "price": str(price), "currency": currency, "is_trial": bool(trial),
            "duration_days": days, "max_ads": limit, "max_photos": photos,
            "interval_sec": interval,
            "allowed_group_ids": json.loads(groups) if isinstance(groups, str) else groups,
            "allowed_category_ids": json.loads(categories) if isinstance(categories, str) else categories,
        }
        bind.execute(set_terms, {"id": sub_id, "terms": terms})
        bind.execute(insert_grant, {
            "subscription_id": sub_id, "user_id": user_id, "tariff_id": tariff_id,
            "terms": terms, "starts_at": starts, "expires_at": expires,
            "payment_id": payment, "granted_by": granted, "created_at": now, "updated_at": now,
        })

    # Tarixiy cheklar uchun migratsiya vaqtidagi shartlar (undan avvalgi
    # tahrirlar ma'lum emas); yangi cheklar yuborilgan zahoti snapshot oladi.
    pay_terms = sa.text("UPDATE payments SET terms = :terms WHERE id = :id").bindparams(
        sa.bindparam("terms", type_=JSONType))
    for pay_id, sub_terms in bind.execute(sa.text("""
        SELECT p.id, s.terms FROM payments p JOIN subscriptions s
          ON s.id = p.subscription_id WHERE p.subscription_id IS NOT NULL
    """)):
        import json
        bind.execute(pay_terms, {"id": pay_id,
                                 "terms": json.loads(sub_terms) if isinstance(sub_terms, str) else sub_terms})

    # Ilgari faol bo'lgan e'lonlar migratsiya zahoti tarqalmaydi.
    active_rows = bind.execute(sa.text("""
        SELECT a.id, a.last_posted_at, t.interval_sec FROM ads a
        JOIN sellers seller ON seller.id = a.seller_id
        JOIN subscriptions s ON s.seller_id = seller.id AND s.status = 'active'
        JOIN tariffs t ON t.id = s.tariff_id
        WHERE a.status = 'active' AND a.next_eligible_at IS NULL
    """)).all()
    for ad_id, last, gap in active_rows:
        # SQLite datetime qaytarishi yoki satr qaytarishi mumkin.
        previous = datetime.fromisoformat(last) if isinstance(last, str) else last
        if previous is not None and previous.tzinfo is None:
            previous = previous.replace(tzinfo=UTC)
        due = max(now, previous or now) + timedelta(seconds=max(60, int(gap or 1800)))
        bind.execute(sa.text("UPDATE ads SET next_eligible_at = :due WHERE id = :id"),
                     {"due": due, "id": ad_id})
    # Arxivdagi kanal qatorlari o'chirilmaydi, ammo eski talab faol qolmasin.
    bind.execute(sa.text("UPDATE counter_settings SET require_subscription = :off"), {"off": False})
    bind.execute(sa.text("UPDATE guard_settings SET require_subscription = :off"), {"off": False})
    bind.execute(sa.text("UPDATE required_channels SET is_active = :off"), {"off": False})

    # Eski guruhda link bilan yig'ilgan N krediti ham direct-add deb qolmasin.
    # InviteEvent va InviteLink tarixini o'chirmaymiz; faqat joriy agregatni
    # unga mos ravishda tuzatamiz. Qo'lda audit tuzatishi qolgani saqlanadi.
    link_counts = bind.execute(sa.text("""
        SELECT ct.group_id, ct.user_id, ct.counted, cs.required_n, COUNT(e.id)
        FROM counter_totals ct JOIN counter_settings cs ON cs.group_id = ct.group_id
        JOIN invite_events e ON e.group_id = ct.group_id AND e.inviter_id = ct.user_id
        WHERE e.source = 'link' AND e.counted = :yes
        GROUP BY ct.group_id, ct.user_id, ct.counted, cs.required_n
    """), {"yes": True}).all()
    for group_id, user_id, count, required_n, link_count in link_counts:
        remaining = max(0, int(count) - int(link_count))
        unlocked = remaining >= int(required_n)
        bind.execute(sa.text("""
            UPDATE counter_totals
            SET counted = :remaining, is_unlocked = :unlocked,
                unlocked_at = CASE WHEN :unlocked THEN unlocked_at ELSE NULL END
            WHERE group_id = :group_id AND user_id = :user_id
        """), {"group_id": group_id, "user_id": user_id,
               "remaining": remaining, "unlocked": unlocked})

    set_sources = sa.text("UPDATE counter_settings SET count_sources = :sources WHERE group_id = :id")\
        .bindparams(sa.bindparam("sources", type_=JSONType))
    for group_id, sources in bind.execute(sa.text("SELECT group_id, count_sources FROM counter_settings")):
        import json
        previous = json.loads(sources) if isinstance(sources, str) else (sources or {})
        bind.execute(set_sources, {"id": group_id, "sources": {**previous, "link": False,
                                                                  "added_by": True}})


def downgrade() -> None:
    op.drop_index("ix_subscription_grants_user_id", table_name="subscription_grants")
    op.drop_index("ix_subscription_grants_subscription_id", table_name="subscription_grants")
    op.drop_table("subscription_grants")
    op.drop_column("free_ads", "admin_paused")
    op.drop_column("ads", "admin_paused")
    op.drop_column("subscriptions", "terms")
    op.drop_column("payments", "terms")
    op.drop_column("tariffs", "interval_sec")
    # Eski kanal yoki link talabi ataylab avtomatik qayta yoqilmaydi.
    # Davrda hisoblangan agregatning manba arxivi qoladi; rollbackdan oldin backup talab.

"""Phase 8: referal cheki, shaxsiy start va bardoshli broadcast.

Revision ID: 8d93a17e623c
Revises: 4f30ae7c912b
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "8d93a17e623c"
down_revision = "4f30ae7c912b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("private_started_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("referral_legacy", sa.Boolean(), nullable=False, server_default=sa.false()))
    # Eski bazada shaxsiy /start tarixini guruhdagi uchrashuvdan ajratib bo'lmaydi:
    # migratsiyadan OLDIN ko'rilgan har qanday akkaunt referal bonusiga yaramaydi.
    # Yangi foydalanuvchi uchun DB standarti false bo'lib qoladi.
    op.execute(sa.text("UPDATE users SET referral_legacy = true"))
    op.add_column("users", sa.Column("broadcast_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("referral_bonus_log") as batch_op:
        batch_op.add_column(sa.Column("reserved_payment_id", sa.Integer()))
        batch_op.add_column(sa.Column("redeemed_at", sa.DateTime(timezone=True)))
        # Boshlang'ich sxemada modeldagi UNIQUE kiritilmay qolgan edi.
        batch_op.create_unique_constraint("uq_referral_bonus_once", ["referral_id"])

    op.add_column("payments", sa.Column("base_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("payments", sa.Column("discount_amount", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("payments", sa.Column("balance_used", sa.Numeric(12, 2), nullable=False, server_default="0"))
    with op.batch_alter_table("payments") as batch_op:
        batch_op.add_column(sa.Column("discount_bonus_id", sa.Integer()))
        batch_op.create_foreign_key("fk_payments_discount_bonus_id_referral_bonus_log",
                                    "referral_bonus_log", ["discount_bonus_id"], ["id"],
                                    ondelete="RESTRICT")
    # Eski cheklar uchun narx snapshot'i saqlanadi; 0 faqat yangi chekning bosh qiymati.
    op.execute(sa.text("UPDATE payments SET base_amount = amount"))

    op.add_column("broadcasts", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("broadcast_targets", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("broadcast_targets", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("broadcast_targets", sa.Column("telegram_message_id", sa.BigInteger()))
    # Eski jadvallardagi dubllar bo'lsa migratsiya xato beradi, mavjud yetkazish
    # jurnalini avtomatik o'chirish xavfsiz emas — avval qo'lda ko'rib chiqilsin.
    with op.batch_alter_table("broadcast_targets") as batch_op:
        batch_op.create_unique_constraint("uq_broadcast_targets_user", ["broadcast_id", "user_id"])


def downgrade() -> None:
    with op.batch_alter_table("broadcast_targets") as batch_op:
        batch_op.drop_constraint("uq_broadcast_targets_user", type_="unique")
        batch_op.drop_column("telegram_message_id")
        batch_op.drop_column("attempts")
        batch_op.drop_column("claimed_at")
    op.drop_column("broadcasts", "next_attempt_at")
    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_constraint("fk_payments_discount_bonus_id_referral_bonus_log", type_="foreignkey")
        batch_op.drop_column("discount_bonus_id")
        batch_op.drop_column("balance_used")
        batch_op.drop_column("discount_amount")
        batch_op.drop_column("base_amount")
    with op.batch_alter_table("referral_bonus_log") as batch_op:
        batch_op.drop_constraint("uq_referral_bonus_once", type_="unique")
        batch_op.drop_column("redeemed_at")
        batch_op.drop_column("reserved_payment_id")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("broadcast_opt_out")
        batch_op.drop_column("referral_legacy")
        batch_op.drop_column("private_started_at")

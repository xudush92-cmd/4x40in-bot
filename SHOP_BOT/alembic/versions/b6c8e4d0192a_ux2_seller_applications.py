"""UX-2: sotuvchilik arizasi (mavjud sotuvchilar va tariflar o'zgarmaydi).

Revision ID: b6c8e4d0192a
Revises: 8d93a17e623c
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b6c8e4d0192a"
down_revision = "8d93a17e623c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seller_applications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("contact_type", sa.String(length=16), nullable=False),
        sa.Column("contact_value", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("seller_id", sa.Integer(), sa.ForeignKey("sellers.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decided_by", sa.BigInteger()),
        sa.Column("reject_reason", sa.String(length=500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_seller_applications_seller_id", "seller_applications", ["seller_id"])
    op.create_index("ix_seller_applications_user_created", "seller_applications", ["user_id", "created_at"])
    op.create_index("ix_seller_applications_status_created", "seller_applications", ["status", "created_at"])
    op.create_index(
        "uq_seller_applications_pending_user", "seller_applications", ["user_id"], unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("uq_seller_applications_pending_user", table_name="seller_applications")
    op.drop_index("ix_seller_applications_status_created", table_name="seller_applications")
    op.drop_index("ix_seller_applications_user_created", table_name="seller_applications")
    op.drop_index("ix_seller_applications_seller_id", table_name="seller_applications")
    op.drop_table("seller_applications")

"""Phase 6: tozalovchi dry-run va xabar siyosati uchun idempotent navbat.

Revision ID: c8a21b6d0f42
Revises: f789aa7b756f
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "c8a21b6d0f42"
down_revision = "f789aa7b756f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Mavjud Phase 4 siyosatlarida qasddan yoqilgan eski post tozalash saqlansin;
    # yangi CleanerSetting esa Python default orqali dry_run=True bilan yaratiladi.
    op.add_column(
        "cleaner_settings",
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "group_message_actions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("planned_action", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_dry_run", sa.Boolean(), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "message_id", name="uq_group_message_action"),
    )
    op.create_index(
        "ix_group_message_actions_group_id", "group_message_actions", ["group_id"]
    )
    op.create_index(
        "ix_group_message_actions_due", "group_message_actions", ["status", "due_at"]
    )
    # Eski bazadagi dublikatdan eng so'nggisini saqlab, qolganini tarixga
    # o'tkazish. Bitta SQL — online ham, offline (--sql) migratsiyada ham ishlaydi.
    op.execute(sa.text(
        "UPDATE permissions SET is_active = false WHERE is_active = true AND EXISTS ("
        "SELECT 1 FROM permissions AS newer WHERE newer.is_active = true "
        "AND newer.id > permissions.id AND newer.user_id = permissions.user_id "
        "AND newer.kind = permissions.kind AND (newer.group_id = permissions.group_id "
        "OR (newer.group_id IS NULL AND permissions.group_id IS NULL)))"
    ))
    op.create_index(
        "uq_permissions_group_active", "permissions", ["user_id", "group_id", "kind"],
        unique=True, postgresql_where=sa.text("is_active AND group_id IS NOT NULL"),
        sqlite_where=sa.text("is_active AND group_id IS NOT NULL"),
    )
    op.create_index(
        "uq_permissions_global_active", "permissions", ["user_id", "kind"],
        unique=True, postgresql_where=sa.text("is_active AND group_id IS NULL"),
        sqlite_where=sa.text("is_active AND group_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_permissions_global_active", table_name="permissions")
    op.drop_index("uq_permissions_group_active", table_name="permissions")
    op.drop_index("ix_group_message_actions_due", table_name="group_message_actions")
    op.drop_index("ix_group_message_actions_group_id", table_name="group_message_actions")
    op.drop_table("group_message_actions")
    with op.batch_alter_table("cleaner_settings") as batch_op:
        batch_op.drop_column("dry_run")

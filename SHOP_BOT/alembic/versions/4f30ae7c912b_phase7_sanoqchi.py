"""Phase 7: xavfsiz sanoqchi, join request va xabar/cheklov jurnali.

Revision ID: 4f30ae7c912b
Revises: c8a21b6d0f42
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "4f30ae7c912b"
down_revision = "c8a21b6d0f42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Matritsada Phase 7dan OLDIN yoqib qo'yilgan counter ham avval dry-run.
    op.add_column("counter_settings", sa.Column(
        "dry_run", sa.Boolean(), nullable=False, server_default=sa.true(),
    ))
    op.add_column("counter_settings", sa.Column(
        "link_member_limit", sa.Integer(), nullable=False, server_default="20",
    ))
    # Eski jadvalda ikki faol havola bo'lsa oxirgisini qoldiramiz. Offline
    # --sql rejimida ham bajariladigan bitta idempotent SQL.
    op.execute(sa.text(
        "UPDATE invite_links SET is_active = false, revoked_at = CURRENT_TIMESTAMP "
        "WHERE is_active = true AND EXISTS (SELECT 1 FROM invite_links AS newer "
        "WHERE newer.is_active = true AND newer.id > invite_links.id "
        "AND newer.group_id = invite_links.group_id AND newer.user_id = invite_links.user_id)"
    ))
    op.create_index(
        "uq_invite_links_active_owner", "invite_links", ["group_id", "user_id"],
        unique=True, postgresql_where=sa.text("is_active"), sqlite_where=sa.text("is_active"),
    )
    op.create_table(
        "counter_join_requests",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("invite_link", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_table(
        "counter_message_checks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("issue", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "message_id", name="uq_counter_message_check"),
    )
    op.create_index("ix_counter_message_checks_group_id", "counter_message_checks", ["group_id"])
    op.create_table(
        "counter_restrictions",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("issue", sa.String(32), nullable=False),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )


def downgrade() -> None:
    op.drop_table("counter_restrictions")
    op.drop_index("ix_counter_message_checks_group_id", table_name="counter_message_checks")
    op.drop_table("counter_message_checks")
    op.drop_table("counter_join_requests")
    op.drop_index("uq_invite_links_active_owner", table_name="invite_links")
    with op.batch_alter_table("counter_settings") as batch_op:
        batch_op.drop_column("link_member_limit")
        batch_op.drop_column("dry_run")

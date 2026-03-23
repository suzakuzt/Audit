"""add normalized alias uniqueness

Revision ID: 20260322_1200
Revises: 20260321_1500
Create Date: 2026-03-22 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260322_1200"
down_revision = "20260321_1500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("alias_entries") as batch_op:
        batch_op.add_column(sa.Column("alias_text_normalized", sa.String(length=255), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, standard_field, alias_text, status FROM alias_entries ORDER BY id ASC")).mappings().all()
    seen: set[tuple[str, str, str]] = set()
    duplicate_ids: list[int] = []
    for row in rows:
        normalized_alias = " ".join(str(row["alias_text"] or "").strip().lower().split())
        connection.execute(
            sa.text("UPDATE alias_entries SET alias_text_normalized = :normalized WHERE id = :id"),
            {"normalized": normalized_alias, "id": row["id"]},
        )
        key = (str(row["standard_field"] or ""), normalized_alias, str(row["status"] or ""))
        if key in seen:
            duplicate_ids.append(int(row["id"]))
        else:
            seen.add(key)

    if duplicate_ids:
        placeholders = ", ".join(str(item) for item in duplicate_ids)
        connection.execute(sa.text(f"DELETE FROM alias_entries WHERE id IN ({placeholders})"))

    with op.batch_alter_table("alias_entries") as batch_op:
        batch_op.alter_column("alias_text_normalized", existing_type=sa.String(length=255), nullable=False)
        batch_op.create_index(op.f("ix_alias_entries_alias_text_normalized"), ["alias_text_normalized"], unique=False)
        batch_op.create_unique_constraint("uq_alias_entries_field_alias_status", ["standard_field", "alias_text_normalized", "status"])


def downgrade() -> None:
    with op.batch_alter_table("alias_entries") as batch_op:
        batch_op.drop_constraint("uq_alias_entries_field_alias_status", type_="unique")
        batch_op.drop_index(op.f("ix_alias_entries_alias_text_normalized"))
        batch_op.drop_column("alias_text_normalized")

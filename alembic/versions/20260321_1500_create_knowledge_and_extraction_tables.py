"""create knowledge and extraction tables

Revision ID: 20260321_1500
Revises: 20260319_1708
Create Date: 2026-03-21 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260321_1500"
down_revision = "20260319_1708"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_prompt_versions_id"), "prompt_versions", ["id"], unique=False)
    op.create_index(op.f("ix_prompt_versions_name"), "prompt_versions", ["name"], unique=False)

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_key", sa.String(length=100), nullable=False),
        sa.Column("output_dir", sa.String(length=500), nullable=True),
        sa.Column("prompt_version_id", sa.Integer(), nullable=True),
        sa.Column("prompt_name", sa.String(length=255), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("ocr_model", sa.String(length=100), nullable=True),
        sa.Column("llm_base_url", sa.String(length=500), nullable=True),
        sa.Column("llm_timeout_seconds", sa.Integer(), nullable=True),
        sa.Column("use_alias_active", sa.Boolean(), nullable=False),
        sa.Column("use_rule_active", sa.Boolean(), nullable=False),
        sa.Column("ocr_enabled", sa.Boolean(), nullable=False),
        sa.Column("force_ocr", sa.Boolean(), nullable=False),
        sa.Column("total_documents", sa.Integer(), nullable=False),
        sa.Column("text_valid_documents", sa.Integer(), nullable=False),
        sa.Column("avg_coverage_rate", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["prompt_version_id"], ["prompt_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key"),
    )
    op.create_index(op.f("ix_extraction_runs_id"), "extraction_runs", ["id"], unique=False)
    op.create_index(op.f("ix_extraction_runs_prompt_version_id"), "extraction_runs", ["prompt_version_id"], unique=False)
    op.create_index(op.f("ix_extraction_runs_run_key"), "extraction_runs", ["run_key"], unique=False)

    op.create_table(
        "extraction_run_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("doc_type", sa.String(length=100), nullable=True),
        sa.Column("extraction_method", sa.String(length=100), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("is_text_valid", sa.Boolean(), nullable=False),
        sa.Column("raw_summary", sa.Text(), nullable=True),
        sa.Column("raw_model_response", sa.Text(), nullable=True),
        sa.Column("warnings_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_extraction_run_documents_filename"), "extraction_run_documents", ["filename"], unique=False)
    op.create_index(op.f("ix_extraction_run_documents_id"), "extraction_run_documents", ["id"], unique=False)
    op.create_index(op.f("ix_extraction_run_documents_run_id"), "extraction_run_documents", ["run_id"], unique=False)

    op.create_table(
        "extraction_run_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("standard_field", sa.String(length=100), nullable=False),
        sa.Column("standard_label_cn", sa.String(length=100), nullable=False),
        sa.Column("source_field_name", sa.String(length=255), nullable=True),
        sa.Column("source_value", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("review_status", sa.String(length=30), nullable=False),
        sa.Column("confirmed_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["extraction_run_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_extraction_run_fields_document_id"), "extraction_run_fields", ["document_id"], unique=False)
    op.create_index(op.f("ix_extraction_run_fields_id"), "extraction_run_fields", ["id"], unique=False)
    op.create_index(op.f("ix_extraction_run_fields_review_status"), "extraction_run_fields", ["review_status"], unique=False)
    op.create_index(op.f("ix_extraction_run_fields_standard_field"), "extraction_run_fields", ["standard_field"], unique=False)

    op.create_table(
        "alias_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("standard_field", sa.String(length=100), nullable=False),
        sa.Column("alias_text", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("extraction_run_field_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["extraction_run_field_id"], ["extraction_run_fields.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_alias_entries_alias_text"), "alias_entries", ["alias_text"], unique=False)
    op.create_index(op.f("ix_alias_entries_extraction_run_field_id"), "alias_entries", ["extraction_run_field_id"], unique=False)
    op.create_index(op.f("ix_alias_entries_id"), "alias_entries", ["id"], unique=False)
    op.create_index(op.f("ix_alias_entries_standard_field"), "alias_entries", ["standard_field"], unique=False)
    op.create_index(op.f("ix_alias_entries_status"), "alias_entries", ["status"], unique=False)

    op.create_table(
        "rule_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("standard_field", sa.String(length=100), nullable=True),
        sa.Column("rule_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("extraction_run_field_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["extraction_run_field_id"], ["extraction_run_fields.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_rule_entries_extraction_run_field_id"), "rule_entries", ["extraction_run_field_id"], unique=False)
    op.create_index(op.f("ix_rule_entries_id"), "rule_entries", ["id"], unique=False)
    op.create_index(op.f("ix_rule_entries_name"), "rule_entries", ["name"], unique=False)
    op.create_index(op.f("ix_rule_entries_standard_field"), "rule_entries", ["standard_field"], unique=False)
    op.create_index(op.f("ix_rule_entries_status"), "rule_entries", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rule_entries_status"), table_name="rule_entries")
    op.drop_index(op.f("ix_rule_entries_standard_field"), table_name="rule_entries")
    op.drop_index(op.f("ix_rule_entries_name"), table_name="rule_entries")
    op.drop_index(op.f("ix_rule_entries_id"), table_name="rule_entries")
    op.drop_index(op.f("ix_rule_entries_extraction_run_field_id"), table_name="rule_entries")
    op.drop_table("rule_entries")

    op.drop_index(op.f("ix_alias_entries_status"), table_name="alias_entries")
    op.drop_index(op.f("ix_alias_entries_standard_field"), table_name="alias_entries")
    op.drop_index(op.f("ix_alias_entries_id"), table_name="alias_entries")
    op.drop_index(op.f("ix_alias_entries_extraction_run_field_id"), table_name="alias_entries")
    op.drop_index(op.f("ix_alias_entries_alias_text"), table_name="alias_entries")
    op.drop_table("alias_entries")

    op.drop_index(op.f("ix_extraction_run_fields_standard_field"), table_name="extraction_run_fields")
    op.drop_index(op.f("ix_extraction_run_fields_review_status"), table_name="extraction_run_fields")
    op.drop_index(op.f("ix_extraction_run_fields_id"), table_name="extraction_run_fields")
    op.drop_index(op.f("ix_extraction_run_fields_document_id"), table_name="extraction_run_fields")
    op.drop_table("extraction_run_fields")

    op.drop_index(op.f("ix_extraction_run_documents_run_id"), table_name="extraction_run_documents")
    op.drop_index(op.f("ix_extraction_run_documents_id"), table_name="extraction_run_documents")
    op.drop_index(op.f("ix_extraction_run_documents_filename"), table_name="extraction_run_documents")
    op.drop_table("extraction_run_documents")

    op.drop_index(op.f("ix_extraction_runs_run_key"), table_name="extraction_runs")
    op.drop_index(op.f("ix_extraction_runs_prompt_version_id"), table_name="extraction_runs")
    op.drop_index(op.f("ix_extraction_runs_id"), table_name="extraction_runs")
    op.drop_table("extraction_runs")

    op.drop_index(op.f("ix_prompt_versions_name"), table_name="prompt_versions")
    op.drop_index(op.f("ix_prompt_versions_id"), table_name="prompt_versions")
    op.drop_table("prompt_versions")

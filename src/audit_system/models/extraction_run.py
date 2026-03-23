from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class ExtractionRun(TimestampMixin, Base):
    __tablename__ = "extraction_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    output_dir: Mapped[str | None] = mapped_column(String(500), nullable=True)
    prompt_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    prompt_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    ocr_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    llm_timeout_seconds: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    use_alias_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    use_rule_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    ocr_enabled: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    force_ocr: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    total_documents: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    text_valid_documents: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    avg_coverage_rate: Mapped[float | None] = mapped_column(Float(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text(), nullable=True)

    prompt_version = relationship("PromptVersion", back_populates="extraction_runs")
    documents = relationship(
        "ExtractionRunDocument",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ExtractionRunDocument(TimestampMixin, Base):
    __tablename__ = "extraction_run_documents"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    doc_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    page_count: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    is_text_valid: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    raw_summary: Mapped[str | None] = mapped_column(Text(), nullable=True)
    raw_model_response: Mapped[str | None] = mapped_column(Text(), nullable=True)
    warnings_text: Mapped[str | None] = mapped_column(Text(), nullable=True)

    run = relationship("ExtractionRun", back_populates="documents")
    fields = relationship(
        "ExtractionRunField",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class ExtractionRunField(TimestampMixin, Base):
    __tablename__ = "extraction_run_fields"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("extraction_run_documents.id", ondelete="CASCADE"),
        index=True,
    )
    standard_field: Mapped[str] = mapped_column(String(100), index=True)
    standard_label_cn: Mapped[str] = mapped_column(String(100), nullable=False)
    source_field_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_value: Mapped[str | None] = mapped_column(Text(), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float(), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    confirmed_value: Mapped[str | None] = mapped_column(Text(), nullable=True)

    document = relationship("ExtractionRunDocument", back_populates="fields")
    alias_entries = relationship("AliasEntry", back_populates="extraction_run_field")
    rule_entries = relationship("RuleEntry", back_populates="extraction_run_field")

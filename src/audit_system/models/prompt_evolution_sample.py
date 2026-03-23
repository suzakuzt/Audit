from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class PromptEvolutionSample(TimestampMixin, Base):
    __tablename__ = "prompt_evolution_samples"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_key: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fragment_versions: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    raw_document: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    ocr_text: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    doc_type_result: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    field_result: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    missing_fields: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    wrong_fields: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    human_correction: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    failure_reasons: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    attribution_summary: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    sample_status: Mapped[str] = mapped_column(String(30), default="failed", index=True, nullable=False)
    value_score: Mapped[int] = mapped_column(Integer(), default=0, nullable=False)
    recurrence_count: Mapped[int] = mapped_column(Integer(), default=1, nullable=False)

    patches = relationship("RulePatch", back_populates="sample", cascade="all, delete-orphan")

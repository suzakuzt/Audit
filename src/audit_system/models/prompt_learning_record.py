from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class PromptLearningRecord(TimestampMixin, Base):
    __tablename__ = "prompt_learning_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_key: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255), index=True)
    prompt_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    doc_type_result: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    field_result: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    human_feedback: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    suggestion_result: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)

    suggestions = relationship("PromptSuggestion", back_populates="learning_record", cascade="all, delete-orphan")

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class PromptSuggestion(TimestampMixin, Base):
    __tablename__ = "prompt_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    learning_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("prompt_learning_records.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    suggestion_type: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    target_scope: Mapped[str] = mapped_column(String(100), default="global", nullable=False)
    suggestion_text: Mapped[str] = mapped_column(Text(), nullable=False)
    why: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    is_adopted: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)

    learning_record = relationship("PromptLearningRecord", back_populates="suggestions")

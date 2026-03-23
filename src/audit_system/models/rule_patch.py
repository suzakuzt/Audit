from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class RulePatch(TimestampMixin, Base):
    __tablename__ = "rule_patches"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sample_id: Mapped[int | None] = mapped_column(ForeignKey("prompt_evolution_samples.id", ondelete="SET NULL"), nullable=True, index=True)
    patch_type: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    target_fragment_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    patch_text: Mapped[str] = mapped_column(Text(), nullable=False)
    impacted_fields: Mapped[str] = mapped_column(Text(), default="[]", nullable=False)
    risk_note: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    metrics_before: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    metrics_after: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    validation_report: Mapped[str] = mapped_column(Text(), default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float(), default=0.0, nullable=False)

    sample = relationship("PromptEvolutionSample", back_populates="patches")

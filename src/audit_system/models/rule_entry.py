from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class RuleEntry(TimestampMixin, Base):
    __tablename__ = "rule_entries"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    standard_field: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(50), default="mapping", nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    extraction_run_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_run_fields.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    extraction_run_field = relationship("ExtractionRunField", back_populates="rule_entries")

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class AliasEntry(TimestampMixin, Base):
    __tablename__ = "alias_entries"
    __table_args__ = (
        UniqueConstraint("standard_field", "alias_text_normalized", "status", name="uq_alias_entries_field_alias_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    standard_field: Mapped[str] = mapped_column(String(100), index=True)
    alias_text: Mapped[str] = mapped_column(String(255), index=True)
    alias_text_normalized: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(nullable=True)
    extraction_run_field_id: Mapped[int | None] = mapped_column(
        ForeignKey("extraction_run_fields.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    extraction_run_field = relationship("ExtractionRunField", back_populates="alias_entries")

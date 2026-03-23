from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from audit_system.db.base import Base
from audit_system.models.mixins import TimestampMixin


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    actor: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    resource: Mapped[str] = mapped_column(String(100), index=True)
    detail: Mapped[str] = mapped_column(Text())

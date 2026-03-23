from sqlalchemy import select
from sqlalchemy.orm import Session

from audit_system.models.audit_log import AuditLog
from audit_system.schemas.audit_log import AuditLogCreate


def create_audit_log(db: Session, payload: AuditLogCreate) -> AuditLog:
    audit_log = AuditLog(**payload.model_dump())
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    return audit_log


def list_audit_logs(db: Session, skip: int = 0, limit: int = 20) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())

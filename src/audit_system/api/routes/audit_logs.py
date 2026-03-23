from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from audit_system.db.session import get_db
from audit_system.schemas.audit_log import AuditLogCreate, AuditLogRead
from audit_system.services.audit_log_service import create_audit_log, list_audit_logs


router = APIRouter()


@router.post("", response_model=AuditLogRead, status_code=status.HTTP_201_CREATED)
def create_audit_log_endpoint(
    payload: AuditLogCreate,
    db: Session = Depends(get_db),
) -> AuditLogRead:
    return create_audit_log(db, payload)


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs_endpoint(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[AuditLogRead]:
    return list_audit_logs(db, skip=skip, limit=limit)
